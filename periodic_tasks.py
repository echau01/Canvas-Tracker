import asyncio
import os
import util
import canvasapi
from canvasapi import Canvas
import discord
from discord.ext import commands
from dotenv import load_dotenv
import traceback

load_dotenv()

# Do *not* put a slash at the end of this path
COURSES_DIRECTORY = "./data/courses"

CANVAS_URL = "https://canvas.ubc.ca/"
CANVAS_TOKEN = os.getenv('CANVAS_TOKEN')
CANVAS_INSTANCE = Canvas(CANVAS_URL, CANVAS_TOKEN)

# Module names and ModuleItem titles are truncated to this length
MAX_IDENTIFIER_LENGTH = 100

RED = 0xff0000

def setup(bot):
    bot.add_cog(Tasks(bot))
    print("Loaded Tasks cog", flush=True)

class Tasks(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.tasks = []
        self.tasks.append(asyncio.get_event_loop().create_task(self.check_canvas_hourly()))
    
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
            await self.check_canvas()
            await asyncio.sleep(3600)
    
    async def check_canvas(self):
        """
        For every folder in COURSES_DIRECTORY we will:
        - get the modules for the Canvas course with ID that matches the folder name
        - compare the modules we retrieved with the modules found in COURSES_DIRECTORY/{course_id}/modules.txt
        - send the names of any modules not in the file to all channels in COURSES_DIRECTORY/{course_id}/watchers.txt
        - update COURSES_DIRECTORY/{course_id}/modules.txt with the modules we retrieved from Canvas
        """
        
        def update_embed(embed, module, num_fields, embed_list):
            """
            Signature: (discord.Embed, Union[canvasapi.module.Module, canvasapi.module.ModuleItem], int, List[discord.Embed]) -> Boolean

            Adds a field to embed containing a hyperlink to given Canvas module/module item. The hyperlink
            is omitted if module does not have the html_url attribute -- only the module's name/title attribute is 
            included in the field.

            If the module's identifier (its name or title) has over MAX_IDENTIFIER_LENGTH characters, we truncate the identifier
            and append an ellipsis (...) so that it has MAX_IDENTIFIER_LENGTH characters.

            The embed object must have at most 24 fields. `num_fields` is the number of fields the embed object has. 
            Note that this function does not (and cannot) update num_fields, since integers are immutable in Python.

            The embed object is appended to embed_list if num_fields is 24.

            This function returns True if the embed object is appended to embed_list. Otherwise, the function returns False.

            Note that Python stores references in lists -- hence, modifying embed after calling
            this function will modify embed_list if embed was added to embed_list.
            """
            if hasattr(module, 'title'):
                field = module.title
            else:
                field = module.name
            
            if len(field) > MAX_IDENTIFIER_LENGTH:
                field = f'{field[:MAX_IDENTIFIER_LENGTH - 3]}...'

            if hasattr(module, 'html_url'):
                field = f'[{field}]({module.html_url})'
            
            if isinstance(module, canvasapi.module.Module):
                embed.add_field(name="Module", value=field, inline=False)
            else:
                embed.add_field(name="Module Item", value=field, inline=False)

            if num_fields == 24:
                embed_list.append(embed)
                return True
            
            return False
        
        def handle_module(module, modules_file, existing_modules, curr_embed, curr_embed_num_fields, embed_list):
            """
            Signature: (canvasapi.module.Module, TextIO, List[str], discord.Embed, int, List[discord.Embed]) -> int
            """
            module_with_newline = module.name + '\n'
            modules_file.write(module_with_newline)

            if not module_with_newline in existing_modules:
                embed_appended = update_embed(curr_embed, module, curr_embed_num_fields, embed_list)
                return 0 if embed_appended else curr_embed_num_fields + 1
            return curr_embed_num_fields
        
        def handle_module_item(item, modules_file, existing_modules, curr_embed, curr_embed_num_fields, embed_list):
            """
            Signature: (canvasapi.module.ModuleItem, TextIO, List[str], discord.Embed, int, List[discord.Embed]) -> int
            """
            if hasattr(item, 'html_url'):
                to_write = item.html_url + '\n'
            else:
                to_write = item.title + '\n'
                
            modules_file.write(to_write)
            if to_write not in existing_modules:
                embed_appended = update_embed(curr_embed, item, curr_embed_num_fields, embed_list)
                return 0 if embed_appended else curr_num_fields + 1
            return curr_embed_num_fields

        if (os.path.exists(COURSES_DIRECTORY)):
            courses = [name for name in os.listdir(COURSES_DIRECTORY)]

            # each folder in the courses directory is named with a course id (which is a positive integer)
            for course_id_str in courses:
                if course_id_str.isdigit():
                    course_id = int(course_id_str)
                    try:
                        course = CANVAS_INSTANCE.get_course(course_id)
                        modules_file = f'{COURSES_DIRECTORY}/{course_id}/modules.txt'
                        watchers_file = f'{COURSES_DIRECTORY}/{course_id}/watchers.txt'
                        
                        print(f'Downloading modules for {course.name}', flush=True)

                        util.create_file_if_not_exists(modules_file)
                        util.create_file_if_not_exists(watchers_file)

                        with open(modules_file, 'r') as m:
                            existing_modules = set(m.readlines())
                        
                        embeds_to_send = []

                        curr_embed = discord.Embed(title=f"New modules found for {course.name}:", color=RED)
                        curr_num_fields = 0

                        with open(modules_file, 'w') as m:
                            for module in course.get_modules():
                                if hasattr(module, 'name'):
                                    curr_num_fields = handle_module(module, m, existing_modules, curr_embed, curr_num_fields, embeds_to_send)
                                    if curr_num_fields == 0:
                                        curr_embed = discord.Embed(title=f"New modules for {course.name} (continued):", color=RED)
                                    
                                    for item in module.get_module_items():
                                        if hasattr(item, 'title'):
                                            curr_num_fields = handle_module_item(item, m, existing_modules, curr_embed, curr_num_fields, embeds_to_send)
                                            if curr_num_fields == 0:
                                                curr_embed = discord.Embed(title=f"New modules for {course.name} (continued):", color=RED)
                        
                        if curr_num_fields:
                            embeds_to_send.append(curr_embed)
                        
                        if embeds_to_send:
                            with open(watchers_file, 'r') as w:
                                for channel_id in w:
                                    channel = self.bot.get_channel(int(channel_id.rstrip()))
                                    for element in embeds_to_send:
                                        await channel.send(embed=element)

                    except Exception:
                        print(traceback.format_exc(), flush=True)
