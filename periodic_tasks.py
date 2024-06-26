import asyncio
import os
import shutil
import traceback
from typing import List, Union

import canvasapi.exceptions
from canvasapi import Canvas
from canvasapi.course import Course
from canvasapi.module import Module, ModuleItem
import discord
from discord.ext import commands
from discord.ext.commands import Bot
from dotenv import load_dotenv

import util
from util import CanvasUtil

load_dotenv()

# Do *not* put a slash at the end of this path
COURSES_DIRECTORY = "./data/courses"

CANVAS_URL = "https://canvas.ubc.ca/"
CANVAS_TOKEN = os.getenv("CANVAS_TOKEN")
CANVAS_INSTANCE = Canvas(CANVAS_URL, CANVAS_TOKEN) if CANVAS_TOKEN else None

# Module names and ModuleItem titles are truncated to this length
MAX_IDENTIFIER_LENGTH = 100
RED = 0xff0000
EMBED_CHAR_LIMIT = 6000


def setup(bot: Bot):
    bot.add_cog(Tasks(bot))
    print("Loaded Tasks cog", flush=True)

    if not CANVAS_TOKEN:
        print("[Error]: Could not find CANVAS_TOKEN variable in .env file", flush=True)


class Tasks(commands.Cog):
    def __init__(self, bot: Bot):
        self.bot = bot
        self.tasks = []
        self.tasks.append(bot.loop.create_task(self.check_canvas_hourly()))
    
    def cog_unload(self):
        for task in self.tasks:
            task.cancel()

    async def check_canvas_hourly(self):
        """
        This function checks the Canvas courses we are tracking every hour, sending any new modules
        to all Discord channels that are tracking those courses.
        """

        await self.bot.wait_until_ready()

        while not self.bot.is_closed():
            if CANVAS_INSTANCE:
                try:
                    await check_canvas(self.bot)
                except Exception:
                    print(traceback.format_exc(), flush=True)
            else:
                print("[Error]: No Canvas instance exists!", flush=True)

            await asyncio.sleep(3600)


async def check_canvas(bot: Bot):
    """
    For every Canvas course being tracked, we retrieve all modules from the course, filter out
    the previously-known modules, and send the new modules into all Discord channels tracking the
    course. The term "watchers" refers to these channels.

    Each course's modules and watchers are stored in a folder on the local filesystem.

    NOTE: the Canvas API distinguishes between a Module and a ModuleItem. In our documentation, though,
    the word "module" can refer to both; we do not distinguish between the two types.
    """
    
    def get_field_value(module: Union[Module, ModuleItem]) -> str:
        """
        This function returns a string that can be added to a Discord embed as a field's value. The
        string contains the module's name/title and, if present, a hyperlink to the module. If the
        module name is too long, we truncate it and add an ellipsis.
        """

        if hasattr(module, "title"):
            field = module.title
        else:
            field = module.name
        
        if len(field) > MAX_IDENTIFIER_LENGTH:
            field = f"{field[:MAX_IDENTIFIER_LENGTH - 3]}..."

        if hasattr(module, "html_url"):
            field = f"[{field}]({module.html_url})"
        
        return field

    def get_embeds(course: Course, modules: List[Union[Module, ModuleItem]]) -> List[discord.Embed]:
        """
        Returns a list of Discord embeds to send to watcher channels.
        """

        embed = discord.Embed(title=f"New modules found for {course.name}:", color=RED)
        embed_list = []

        for module in modules:
            field_value = get_field_value(module)
            field_name = "Module" if isinstance(module, Module) else "Module Item"
            field_length = len(field_name) + len(field_value)

            if len(embed.fields) >= 25 or field_length + len(embed) > EMBED_CHAR_LIMIT:
                embed_list.append(embed)
                embed = discord.Embed(title=f"New modules found for {course.name} (continued):", color=RED)

            embed.add_field(name=field_name, value=field_value, inline=False)

        if len(embed.fields) != 0:
            embed_list.append(embed)

        return embed_list
    
    async def send_embeds_and_cleanup_watchers_file(embed_list: List[discord.Embed], watchers_file_path: str):
        """
        Sends all embeds in embed_list to all valid Discord text channels listed in the watchers
        file inside the given course directory.

        We remove any line in the watchers file that is not a valid Discord text channel ID.
        """

        with open(watchers_file_path, "r") as f:
            channel_ids = f.read().splitlines()

        with open(watchers_file_path, "w") as f:
            for channel_id in channel_ids:
                channel = bot.get_channel(int(channel_id))

                if channel:
                    f.write(channel_id + "\n")

                    for element in embed_list:
                        await channel.send(embed=element)

    def get_new_modules(retrieved_modules: List[Union[Module, ModuleItem]],
                        course_id: str) -> List[Union[Module, ModuleItem]]:
        modules_file = CanvasUtil.get_modules_file_path(course_id)
        util.ensure_file_exists(modules_file)

        with open(modules_file, 'r') as m:
            existing_modules = set(m.read().splitlines())

        return list(filter(lambda module: str(module.id) not in existing_modules, retrieved_modules))

    def ensure_course_folder_name_is_correct(course_id: str, current_course_folder_name: str) -> str:
        current_course_directory = f"{COURSES_DIRECTORY}/{current_course_folder_name}"
        course_directory = CanvasUtil.get_course_directory(course_id)
        if current_course_directory != course_directory:
            os.rename(current_course_directory, course_directory)

        return course_directory

    async def remove_inaccessible_course(discord_bot: Bot, course_directory: str):
        try:
            with open(CanvasUtil.get_course_name_file_path_by_course_dir(course_directory), 'r') as f:
                course_name = f.readline().strip('\n')
        except FileNotFoundError:
            course_name = "<Course name not found>"

        try:
            with open(CanvasUtil.get_watchers_file_path_by_course_dir(course_directory), 'r') as w:
                for channel_id in w:
                    channel = discord_bot.get_channel(int(channel_id.rstrip()))

                    if channel:
                        await channel.send(f"Removing course {course_name} (ID: {course_directory.split('/')[-1]}) "
                                           f"from courses being tracked; course access denied.")
        except FileNotFoundError:
            pass

        shutil.rmtree(course_directory)

    async def retrieve_and_send_new_modules(course_id: str):
        try:
            course = CANVAS_INSTANCE.get_course(int(course_id_str))
        except (canvasapi.exceptions.InvalidAccessToken, canvasapi.exceptions.Unauthorized,
                canvasapi.exceptions.Forbidden):
            raise InaccessibleCanvasCourseException()

        CanvasUtil.store_course_name_locally(course_id, course.name)

        print(f"Downloading modules for {course.name}", flush=True)
        all_modules = CanvasUtil.get_modules(course)
        embeds_to_send = get_embeds(course, get_new_modules(all_modules, course_id))

        watchers_file = CanvasUtil.get_watchers_file_path_by_course_id(course_id)
        util.ensure_file_exists(watchers_file)
        await send_embeds_and_cleanup_watchers_file(embeds_to_send, watchers_file)

        # Delete the course directory if there are no more channels watching the course.
        if os.stat(watchers_file).st_size == 0:
            shutil.rmtree(CanvasUtil.get_course_directory(course_id))
        else:
            CanvasUtil.write_modules_to_file(CanvasUtil.get_modules_file_path(course_id), all_modules)

    if os.path.exists(COURSES_DIRECTORY):
        for course_folder_name in os.listdir(COURSES_DIRECTORY):
            course_id_str = course_folder_name.split()[0]
            if course_id_str.isdigit():
                course_dir = ensure_course_folder_name_is_correct(course_id_str, course_folder_name)

                try:
                    await retrieve_and_send_new_modules(course_id_str)
                except InaccessibleCanvasCourseException:
                    await remove_inaccessible_course(bot, course_dir)


class InaccessibleCanvasCourseException(Exception):
    pass
