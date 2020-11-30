import asyncio
import copy
import os
import shutil
import traceback
from typing import List, Set, TextIO, Tuple, Union

import canvasapi
from canvasapi import Canvas
from canvasapi.module import Module, ModuleItem
import discord
from discord.ext import commands
from discord.ext.commands import Bot
from dotenv import load_dotenv

import util

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
    - send the names of any modules not in the file to all channels in COURSES_DIRECTORY/{course_id}/watchers.txt
    - update COURSES_DIRECTORY/{course_id}/modules.txt with the modules we retrieved from Canvas
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

        If the module's identifier (its name or title) has over MAX_IDENTIFIER_LENGTH characters, we truncate the identifier
        and append an ellipsis (...) so that the length does not exceed the maximum.

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
        
        if isinstance(module, canvasapi.module.Module):
            embed.add_field(name="Module", value=field_value, inline=False)
        else:
            embed.add_field(name="Module Item", value=field_value, inline=False)

        if len(embed.fields) == 25:
            embed_list.append(copy.deepcopy(embed))
            embed.clear_fields()
            embed.title = f"New modules found for {course.name} (continued):"
    
    def handle_module(module: Union[Module, ModuleItem], modules_file: TextIO, existing_file_contents: Set[str], 
                      embed: discord.Embed, embed_list: List[discord.Embed]):
        """
        Writes given module or module item to modules_file. This function assumes that:
        - modules_file has already been opened in write/append mode.
        - module has the "name" attribute if it is an instance of canvasapi.module.Module.
        - module has the "html_url" attribute or the "title" attribute if it is an instance of canvasapi.module.ModuleItem.

        existing_file_contents contains all of the contents of the pre-existing modules file (or is empty 
        if the modules file has just been created).

        This function updates embed and embed_list depending on whether existing_file_contents contains the
        given module.
        
        NOTE: changes to embed and embed_list will persist outside this function.
        """
        if isinstance(module, canvasapi.module.Module):
            to_write = module.name
        else:
            if hasattr(module, 'html_url'):
                to_write = module.html_url
            else:
                to_write = module.title
            
        modules_file.write(to_write + '\n')

        if not to_write in existing_modules:
            update_embed(embed, module, embed_list)
    
    async def send_embeds(channel_ids_file: TextIO, embed_list: List[discord.Embed]):
        """
        Sends all embeds in embed_list to all valid Discord text channels in channel_ids_file.
        We remove any line in channel_ids_file that is not a valid Discord text channel ID.
        """
        with open(channel_ids_file, 'r') as f:
            channel_ids = f.read().splitlines()
        
        with open(channel_ids_file, 'w') as f:
            for channel_id in channel_ids:
                channel = bot.get_channel(int(channel_id))
                if channel:
                    f.write(channel_id + '\n')
                    for element in embeds_to_send:
                        await channel.send(embed=element)

    if (os.path.exists(COURSES_DIRECTORY)):
        courses = [name for name in os.listdir(COURSES_DIRECTORY)]

        # each folder in the courses directory is named with a course id (which is a positive integer)
        for course_id_str in courses:
            if course_id_str.isdigit():
                course_id = int(course_id_str)
                modules_file = f'{COURSES_DIRECTORY}/{course_id}/modules.txt'
                watchers_file = f'{COURSES_DIRECTORY}/{course_id}/watchers.txt'
                
                try:
                    course = CANVAS_INSTANCE.get_course(course_id)
                    
                    print(f'Downloading modules for {course.name}', flush=True)

                    util.create_file_if_not_exists(modules_file)
                    util.create_file_if_not_exists(watchers_file)

                    with open(modules_file, 'r') as m:
                        existing_modules = set(m.read().splitlines())
                    
                    embeds_to_send = []

                    embed = discord.Embed(title=f"New modules found for {course.name}:", color=RED)

                    with open(modules_file, 'w') as m:
                        for module in course.get_modules():
                            if hasattr(module, 'name'):
                                handle_module(module, m, existing_modules, embed, embeds_to_send)
                                
                                for item in module.get_module_items():
                                    if hasattr(item, 'title'):
                                        handle_module(item, m, existing_modules, embed, embeds_to_send)
                    
                    if len(embed.fields) != 0:
                        embeds_to_send.append(embed)
                    
                    await send_embeds(watchers_file, embeds_to_send)
                
                except canvasapi.exceptions.InvalidAccessToken:
                    # Delete course directory if we no longer have permission to access the Canvas course.
                    with open(watchers_file, 'r') as w:
                        for channel_id in w:
                            channel = bot.get_channel(int(channel_id.rstrip()))
                            if channel:
                                await channel.send(f"Removing course with ID {course_id} from courses being tracked; course access denied.")
                    shutil.rmtree(f'{COURSES_DIRECTORY}/{course_id}')
                except Exception:
                    print(traceback.format_exc(), flush=True)
