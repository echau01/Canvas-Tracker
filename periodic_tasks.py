import asyncio
import os
import util
from canvasapi import Canvas
from discord.ext import commands
from dotenv import load_dotenv
import traceback

load_dotenv()

# Do *not* put a slash at the end of this path
COURSES_DIRECTORY = "./data/courses"

CANVAS_URL = "https://canvas.ubc.ca/"
CANVAS_TOKEN = os.getenv('CANVAS_TOKEN')
CANVAS_INSTANCE = Canvas(CANVAS_URL, CANVAS_TOKEN)

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

        def helper(s, perm_list, temp_list, known_list, acc_length, acc_length_limit, s_length_limit):
            """
            Function signature: (str, list of str, list of str, list of str, int, int, int) -> bool

            If s is not in known_list, then the string '* {s}' is appended to temp_list no matter what. However, before
            we append the string to the list:
            - if len(s) exceeds s_length_limit, then s is first truncated to have length s_length_limit - 6.
              An ellipsis and a newline character (...\n) are then appended to s so that s has length s_length_limit - 2. 
              As a result, '* {s}' has length s_length_limit.
            - if acc_length + len(s) + 2 > acc_length_limit, then:
                - all the elements of temp_list are concatenated, and the result is appended to perm_list.
                - temp_list is cleared.

            This function modifies perm_list and temp_list only.
            """
            if not s in known_list:
                if len(s) > s_length_limit:
                    s = s[:s_length_limit - 6] + '...\n'
                if len(s) + 2 + acc_length > acc_length_limit:
                    perm_list.append(''.join(temp_list))
                    temp_list.clear()
                temp_list.append(f'* {s}')
        
        def get_total_str_length(prev_length, los):
            """
            Returns the total length of the strings in los, assuming the following:
            - los contains at least one string.
            - if los contains more than 1 string, then prev_length is the total length of every 
              string in los except the last one.
            """
            if len(los) == 1:
                return len(los[0])
            else:
                return prev_length + len(los[len(los) - 1])


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
                            
                        # This list contains Canvas module names that are not contained
                        # in the existing modules read from the modules file. 
                        # 
                        # Discord has a message limit of 2000 characters.
                        # Each newline character counts as a character.
                        # The messages sent by the bot will have the following format:
                        # ```\n{element}\n``` for each element in differences
                        #
                        # Therefore, each element has a maximum size of 1992.
                        differences = []
                        
                        # A temporary list where we store names of modules not found
                        # in existing_modules. Each element has the form '* {module.name}\n'
                        temp_diff = []

                        # The total length of all strings in the temp_diff list.
                        temp_diff_str_length = 0

                        # All elements in temp_diff are truncated to this length
                        max_elem_length = 120

                        with open(modules_file, 'w') as m:
                            for module in course.get_modules():
                                if hasattr(module, 'name'):
                                    module_with_newline = module.name + '\n'
                                    m.write(module_with_newline)
                                    helper(module_with_newline, differences, temp_diff, existing_modules, temp_diff_str_length, 1992, max_elem_length)

                                    if temp_diff:
                                        temp_diff_str_length = get_total_str_length(temp_diff_str_length, temp_diff)
                                    
                                    for item in module.get_module_items():
                                        if hasattr(item, 'title'):
                                            item_with_newline = item.title + '\n'
                                            m.write(item_with_newline)
                                            helper(item_with_newline, differences, temp_diff, existing_modules, temp_diff_str_length, 1992, max_elem_length)
                                            
                                            if temp_diff:
                                                temp_diff_str_length = get_total_str_length(temp_diff_str_length, temp_diff)
                        
                        # Get any other strings in temp_diff into differences
                        if temp_diff:
                            differences.append(''.join(temp_diff))
                            temp_diff.clear()
                        
                        if differences:
                            with open(watchers_file, 'r') as w:
                                for channel_id in w:
                                    channel = self.bot.get_channel(int(channel_id.rstrip()))
                                    await channel.send(f'New modules found for {course.name}:')
                                    for element in differences:
                                        await channel.send(f'```\n{element}\n```')

                    except Exception:
                        print(traceback.format_exc(), flush=True)
