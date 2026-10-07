import asyncio
import sqlite3
from os import getenv

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import MessageEntityType
from aiogram.types import InputMediaPhoto
from aiogram.types import Message as TGMessage
from aiogram.types import MessageEntity, URLInputFile
from dotenv import load_dotenv
from pymax import ExtraConfig, Message, WebClient
from pymax.types import PhotoAttachment
from pymax.types.domain.message import ForwardLink, ReplyLink

load_dotenv()

BOT_TOKEN = getenv("BOT_TOKEN")
PROXY = getenv("PROXY")
assert BOT_TOKEN
MAX_CHAT_ID = -68672416579807
TG_CHANNEL_ID = -1004361825573

client = WebClient("max.db")
bot = Bot(
    BOT_TOKEN,
    session=AiohttpSession(proxy=PROXY),
)
dispatcher = Dispatcher()

con = sqlite3.connect("msg.db")
cur = con.cursor()

cur.execute("""CREATE TABLE IF NOT EXISTS messages (
max_id INTEGER PRIMARY KEY,
tg_id INTEGER NOT NULL
)""")


def len16(text: str):
    return len(text.encode("utf-16-le")) // 2


@client.on_message()
async def on_message(message: Message, client: WebClient, force=False):
    if message.chat_id != MAX_CHAT_ID and not force or not message.sender:
        return

    sender = await client.get_user(message.sender)
    if not sender:
        return
    name = sender.names[0].name
    if not name:
        return

    is_forwarded = False
    forwarded_name: str | None = None
    if type(message.link) is ForwardLink:
        is_forwarded = True
        message = message.link.message
        if not message.sender:
            return
        forwarded_from = await client.get_user(message.sender)
        if not forwarded_from:
            return
        forwarded_name = forwarded_from.names[0].name
        if not forwarded_name:
            return

    text = f"{name}"
    entities = [
        MessageEntity(type=MessageEntityType.BOLD, offset=0, length=len16(name)),
    ]
    toffset = len16(name)

    if is_forwarded:
        toffset += len16("\n")
        content = f"Переслано от\n{forwarded_name}"
        text += f"\n{content}"
        entities.append(
            MessageEntity(
                type=MessageEntityType.ITALIC,
                offset=toffset,
                length=len16(content),
            )
        )
        toffset += len16(content)

    if message.text:
        toffset += len16("\n")
        text += f"\n{message.text}"
        entities.append(
            MessageEntity(
                type=MessageEntityType.EXPANDABLE_BLOCKQUOTE,
                offset=toffset,
                length=len16(message.text),
            )
        )

    entities += [
        MessageEntity(type=i.type, offset=toffset + i.from_, length=i.length)
        for i in message.elements
        if i.from_ and i.length
    ]

    reply_to_message_id: int | None = None
    if type(message.link) is ReplyLink:
        max_id = message.link.message.id
        cur.execute("SELECT tg_id FROM messages WHERE max_id = ?", (max_id,))
        result = cur.fetchone()
        if result:
            reply_to_message_id = result[0]

    tg_message: TGMessage | None = None
    supported_attaches = [
        i for i in message.attaches if type(i) is PhotoAttachment and i.preview_data
    ]
    if len(supported_attaches) == 1:
        attach = supported_attaches[0]
        tg_message = await bot.send_photo(
            TG_CHANNEL_ID,
            URLInputFile(
                attach.base_url,
            ),
            caption=text,
            caption_entities=entities,
            reply_to_message_id=reply_to_message_id,
        )
    elif len(supported_attaches) > 1:
        tg_message = (
            await bot.send_media_group(
                TG_CHANNEL_ID,
                [
                    InputMediaPhoto(
                        media=URLInputFile(attach.base_url),
                        caption=text if i == 0 else None,
                        caption_entities=entities if i == 0 else None,
                    )
                    for i, attach in enumerate(message.attaches)
                    if type(attach) is PhotoAttachment and attach.preview_data
                ],
                reply_to_message_id=reply_to_message_id,
            )
        )[0]
    else:
        tg_message = await bot.send_message(
            TG_CHANNEL_ID,
            text,
            entities=entities,
            reply_to_message_id=reply_to_message_id,
        )

    cur.execute(
        "INSERT INTO messages(max_id, tg_id) VALUES (?, ?)",
        (message.id, tg_message.message_id),
    )
    con.commit()


async def fetch_and_send_last_messages(client: WebClient):
    cur.execute("SELECT max_id FROM messages ORDER BY rowid DESC LIMIT 1")
    result = cur.fetchone()
    if not result:
        return

    last_message_id = result[0]
    last_message = await client.get_message(MAX_CHAT_ID, last_message_id)
    if not last_message:
        return

    messages = await client.fetch_history(MAX_CHAT_ID, backward_time=last_message.time)
    for i in messages[1:]:
        await on_message(i, client, True)  # type: ignore


@client.on_start()
async def on_start(client: WebClient):
    await fetch_and_send_last_messages(client)


async def main():
    await client.start()
    con.commit()
    con.close()


if __name__ == "__main__":
    asyncio.run(main())
