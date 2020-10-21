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
    
async def check_canvas(bot):
    """
    For every folder in COURSES_DIRECTORY we will:
    - get the modules for the Canvas course with ID that matches the folder name
    - compare the modules we retrieved with the modules found in COURSES_DIRECTORY/{course_id}/modules.txt
    - send the names of any modules not in the file to all channels in COURSES_DIRECTORY/{course_id}/watchers.txt
    - update COURSES_DIRECTORY/{course_id}/modules.txt with the modules we retrieved from Canvas
    """
    
    def get_field_value(module):
        """
        Signature: Union[canvasapi.module.Module, canvasapi.module.ModuleItem] -> str

        This function returns a string that can be added to a Discord embed as a field's value. The returned
        string contains the module's name/title attribute (depending on which one it has), as well
        as a hyperlink to the module (if the module has the html_url attribute). If the module's name/title exceeds 
        MAX_IDENTIFIER_LENGTH characters, we truncate it and append an ellipsis (...) so that the name/title has 
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
    
    def update_embed(embed, module, num_fields, embed_list):
        """
        Signature: (discord.Embed, Union[canvasapi.module.Module, canvasapi.module.ModuleItem], int, List[discord.Embed]) -> (discord.Embed, int)

        Adds a field to embed containing information about given module. The field includes the module's name or title,
        as well as a hyperlink to the module if one exists.

        If the module's identifier (its name or title) has over MAX_IDENTIFIER_LENGTH characters, we truncate the identifier
        and append an ellipsis (...) so that it has MAX_IDENTIFIER_LENGTH characters.

        The embed object that is passed in must have at most 24 fields. Use the parameter `num_fields` to specify the number 
        of fields the embed object has.

        The embed object is appended to embed_list in two cases:
        - if adding the new field will cause the embed to exceed EMBED_CHAR_LIMIT characters in length, the embed is appended to embed_list first. 
            Then, we create a new embed and add the field to the new embed.
        - if the embed has 25 fields after adding the new field, we append embed to embed_list.

        Note that Python stores references in lists -- hence, modifying the content of the embed variable after calling
        this function will modify embed_list if embed was added to embed_list.

        This function returns a tuple (embed, num_fields) containing the updated values of embed and num_fields.
        
        NOTE: changes to embed_list will persist outside this function, but changes to embed and num_fields 
        may not be reflected outside this function. The caller should update (reassign) the values that were passed 
        in to embed and num_fields using the tuple returned by this function. A reassignment of embed will not
        change the contents of embed_list.
        """
        field_value = get_field_value(module)
        
        # Note: 11 is the length of the string "Module Item"
        if 11 + len(field_value) + len(embed) > EMBED_CHAR_LIMIT:
            embed_list.append(embed)
            embed = discord.Embed(title=f"New modules for {course.name} (continued):", color=RED)
            num_fields = 0
        
        if isinstance(module, canvasapi.module.Module):
            embed.add_field(name="Module", value=field_value, inline=False)
        else:
            embed.add_field(name="Module Item", value=field_value, inline=False)

        num_fields += 1

        if num_fields == 25:
            embed_list.append(embed)
            embed = discord.Embed(title=f"New modules for {course.name} (continued):", color=RED)
            num_fields = 0
        
        return (embed, num_fields)
    
    def handle_module(module, modules_file, existing_modules, curr_embed, curr_embed_num_fields, embed_list):
        """
        Signature: (Union[canvasapi.module.Module, canvasapi.module.ModuleItem], TextIO, List[str], 
        discord.Embed, int, List[discord.Embed]) -> Tuple[discord.Embed, int]

        Writes given module or module item to modules_file. This function assumes that:
        - modules_file has already been opened in write/append mode.
        - module has the "name" attribute if it is an instance of canvasapi.module.Module.
        - module has the "html_url" attribute or the "title" attribute if it is an instance of canvasapi.module.ModuleItem.

        existing_modules contains contents of the pre-existing modules file (or is empty if the modules file has just been created)

        This function updates curr_embed, curr_embed_num_fields, and embed_list depending on whether existing_modules already
        knows about the given module item. 
        
        The function returns a tuple (curr_embed, curr_embed_num_fields) containing the updated values of curr_embed and curr_embed_num_fields.
        
        NOTE: changes to embed_list will persist outside this function, but changes to curr_embed and curr_embed_num_fields may not be 
        reflected outside this function. The caller should update the values that were passed in to curr_embed and curr_embed_num_fields 
        using the tuple returned by this function.
        """
        if isinstance(module, canvasapi.module.Module):
            to_write = module.name + '\n'
        else:
            if hasattr(module, 'html_url'):
                to_write = module.html_url + '\n'
            else:
                to_write = module.title + '\n'
            
        modules_file.write(to_write)

        if not to_write in existing_modules:
            embed_num_fields_tuple = update_embed(curr_embed, module, curr_embed_num_fields, embed_list)
            curr_embed = embed_num_fields_tuple[0]
            curr_embed_num_fields = embed_num_fields_tuple[1]
        
        return (curr_embed, curr_embed_num_fields)

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
                                embed_num_fields_tuple = handle_module(module, m, existing_modules, curr_embed, curr_num_fields, embeds_to_send)
                                curr_embed = embed_num_fields_tuple[0]
                                curr_num_fields = embed_num_fields_tuple[1]
                                
                                for item in module.get_module_items():
                                    if hasattr(item, 'title'):
                                        embed_num_fields_tuple = handle_module(item, m, existing_modules, curr_embed, curr_num_fields, embeds_to_send)
                                        curr_embed = embed_num_fields_tuple[0]
                                        curr_num_fields = embed_num_fields_tuple[1]
                    
                    if curr_num_fields:
                        embeds_to_send.append(curr_embed)
                    
                    if embeds_to_send:
                        with open(watchers_file, 'r') as w:
                            for channel_id in w:
                                channel = bot.get_channel(int(channel_id.rstrip()))
                                for element in embeds_to_send:
                                    await channel.send(embed=element)

                except Exception:
                    print(traceback.format_exc(), flush=True)
