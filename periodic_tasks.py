import asyncio
import copy
import os
import shutil
import traceback
from typing import List, Union

import canvasapi.exceptions
from canvasapi import Canvas
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
CANVAS_TOKEN = os.getenv('CANVAS_TOKEN')
CANVAS_INSTANCE = Canvas(CANVAS_URL, CANVAS_TOKEN)

# Module names and ModuleItem titles are truncated to this length
MAX_IDENTIFIER_LENGTH = 100

RED = 0xff0000

EMBED_CHAR_LIMIT = 6000


def setup(bot):
    bot.add_cog(Tasks(bot))
    print("Loaded Tasks cog", flush=True)


class Tasks(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.tasks = []
        self.tasks.append(bot.loop.create_task(self.check_canvas_hourly()))
    
    def cog_unload(self):
        for task in self.tasks:
            task.cancel()

    async def check_canvas_hourly(self):
        """
        Every folder in COURSES_DIRECTORY is named after the ID of a Canvas course we are tracking.
        This function checks the Canvas courses we are tracking every hour. Any updates to the
        names of the courses' modules since the last hour are sent to all Discord channels tracking 
        those courses.
        """

        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            await check_canvas(self.bot)
            await asyncio.sleep(3600)


async def check_canvas(bot: Bot):
    """
    For every folder in COURSES_DIRECTORY we will:
    - get the modules for the Canvas course with ID that matches the folder name
    - compare the modules we retrieved with the modules found in COURSES_DIRECTORY/{course_id}/modules.txt
    - use the given bot to send the names of any modules not in the above file to all channels in
    COURSES_DIRECTORY/{course_id}/watchers.txt
    - update COURSES_DIRECTORY/{course_id}/modules.txt with the modules we retrieved from Canvas

    NOTE: the Canvas API distinguishes between a Module and a ModuleItem. In our documentation, though,
    the word "module" can refer to both; we do not distinguish between the two types.
    """
    
    def get_field_value(module: Union[Module, ModuleItem]) -> str:
        """
        This function returns a string that can be added to a Discord embed as a field's value. The returned
        string contains the module's name/title attribute (depending on which one it has), as well
        as a hyperlink to the module (if the module has the html_url attribute). If the module's name/title exceeds 
        MAX_IDENTIFIER_LENGTH characters, we truncate it and append an ellipsis (...) so that the name/title has exactly
        MAX_IDENTIFIER_LENGTH characters.
        """

        if hasattr(module, 'title'):
            field = module.title
        else:
            field = module.name
        
        if len(field) > MAX_IDENTIFIER_LENGTH:
            field = f'{field[:MAX_IDENTIFIER_LENGTH - 3]}...'

        if hasattr(module, 'html_url'):
            field = f'[{field}]({module.html_url})'
        
        return field
    
    def update_embed(embed: discord.Embed, module: Union[Module, ModuleItem], embed_list: List[discord.Embed]):
        """
        Adds a field to embed containing information about given module. The field includes the module's name or title,
        as well as a hyperlink to the module if one exists.

        If the module's identifier (its name or title) has over MAX_IDENTIFIER_LENGTH characters, we truncate the
        identifier and append an ellipsis (...) so that the length does not exceed the maximum.

        The embed object that is passed in must have at most 24 fields.

        A deep copy of the embed object is appended to embed_list in two cases:
        - if adding the new field will cause the embed to exceed EMBED_CHAR_LIMIT characters in length
        - if the embed has 25 fields after adding the new field, we append embed to embed_list.
        In both cases, we clear all of the original embed's fields after adding the embed copy to embed_list.
        
        NOTE: changes to embed and embed_list will persist outside this function.
        """

        field_value = get_field_value(module)
        
        # Note: 11 is the length of the string "Module Item"
        if 11 + len(field_value) + len(embed) > EMBED_CHAR_LIMIT:
            embed_list.append(copy.deepcopy(embed))
            embed.clear_fields()
            embed.title = f"New modules found for {course.name} (continued):"
        
        if isinstance(module, Module):
            embed.add_field(name="Module", value=field_value, inline=False)
        else:
            embed.add_field(name="Module Item", value=field_value, inline=False)

        if len(embed.fields) == 25:
            embed_list.append(copy.deepcopy(embed))
            embed.clear_fields()
            embed.title = f"New modules found for {course.name} (continued):"

    def get_embeds(modules: List[Union[Module, ModuleItem]]) -> List[discord.Embed]:
        """
        Returns a list of Discord embeds to send to live channels.
        """

        embed = discord.Embed(title=f"New modules found for {course.name}:", color=RED)

        embed_list = []

        for module in modules:
            update_embed(embed, module, embed_list)

        if len(embed.fields) != 0:
            embed_list.append(embed)

        return embed_list
    
    async def send_embeds(course_directory: str, embed_list: List[discord.Embed]):
        """
        Sends all embeds in embed_list to all valid Discord text channels listed in the watchers
        file inside the given course directory.

        We remove any line in the watchers file that is not a valid Discord text channel ID. If
        the watchers file does not contain any valid text channel IDs, we also delete the course directory
        since the course has no valid "watchers".
        
        This function assumes that the given directory actually contains a watchers file.
        """
        
        watchers_file = f'{course_directory}/watchers.txt'
        
        with open(watchers_file, 'r') as f:
            channel_ids = f.read().splitlines()
        
        with open(watchers_file, 'w') as f:
            for channel_id in channel_ids:
                channel = bot.get_channel(int(channel_id))

                if channel:
                    f.write(channel_id + '\n')

                    for element in embed_list:
                        await channel.send(embed=element)
        
        if os.stat(watchers_file).st_size == 0:
            shutil.rmtree(course_directory)

    if os.path.exists(COURSES_DIRECTORY):
        courses = [name for name in os.listdir(COURSES_DIRECTORY)]

        # each folder in the courses directory is named with a course id (which is a positive integer)
        for course_id_str in courses:
            if course_id_str.isdigit():
                course_id = int(course_id_str)
                course_dir = f'{COURSES_DIRECTORY}/{course_id}'
                modules_file = f'{course_dir}/modules.txt'
                watchers_file = f'{course_dir}/watchers.txt'
                
                try:
                    course = CANVAS_INSTANCE.get_course(course_id)
                    
                    print(f'Downloading modules for {course.name}', flush=True)

                    util.create_file(modules_file)
                    util.create_file(watchers_file)

                    with open(modules_file, 'r') as m:
                        existing_modules = set(m.read().splitlines())

                    all_modules = CanvasUtil.get_modules(course)
                    differences = list(filter(lambda module: str(module.id) not in existing_modules, all_modules))
                    embeds_to_send = get_embeds(differences)
                    
                    await send_embeds(course_dir, embeds_to_send)
                    CanvasUtil.write_modules(modules_file, all_modules)
                
                except canvasapi.exceptions.InvalidAccessToken:
                    with open(watchers_file, 'r') as w:
                        for channel_id in w:
                            channel = bot.get_channel(int(channel_id.rstrip()))

                            if channel:
                                await channel.send(f"Removing course with ID {course_id} from courses "
                                                   f"being tracked; course access denied.")

                    # Delete course directory if we no longer have permission to access the Canvas course.
                    shutil.rmtree(course_dir)

                except Exception:
                    print(traceback.format_exc(), flush=True)
