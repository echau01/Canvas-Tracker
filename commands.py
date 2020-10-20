import traceback
import util
from discord.ext import commands
import canvasapi
from canvasapi import Canvas
import periodic_tasks
import shutil
import os

class Bot_Management(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def reload(self, ctx):
        """
        Reloads extensions.

        `!reload`
        """
        self.bot.reload_extension("commands")
        self.bot.reload_extension("periodic_tasks")
        await ctx.send("Bot reloaded!")

    @commands.command(hidden=True)
    @commands.has_role("Bot Controller")
    async def stop(self, ctx):
        """
        Stops the bot.

        `!stop`
        """
        await ctx.send("Shutting down. Goodbye.")
        await self.bot.close()

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.errors.MissingRole):
            await ctx.send("You do not have the required role.")
        else:
            await ctx.send(f"```\n{traceback.format_exception(type(error), error, error.__traceback__)}\n```")


class Main(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def track(self, ctx, *args):
        """
        Configure the current text channel to receive an update when a course module is published on Canvas.

        `!track <enable | disable> <course_id>`
        """

        if len(args) != 2:
            await ctx.send("Usage: `!track <enable | disable> <course_id>`")
        elif args[0] != 'enable' and args[0] != 'disable':
            await ctx.send("Usage: `!track <enable | disable> <course_id>`")
        else:
            modules_file = f'{periodic_tasks.COURSES_DIRECTORY}/{args[1]}/modules.txt'
            watchers_file = f'{periodic_tasks.COURSES_DIRECTORY}/{args[1]}/watchers.txt'
            try:
                course = periodic_tasks.CANVAS_INSTANCE.get_course(args[1])
                if args[0] == 'enable':
                    # The watchers file contains all the channels watching the course
                    added = await self.store_channel_in_file(ctx.channel, watchers_file)
                    util.create_file_if_not_exists(modules_file)

                    if added:
                        await ctx.send(f'This channel is now tracking {course.name}.')
                        
                        # We will only update the modules if modules_file is empty.
                        if os.stat(modules_file).st_size == 0:
                            with open(modules_file, 'w') as f:
                                for module in course.get_modules():
                                    if hasattr(module, 'name'):
                                        f.write(module.name + '\n')

                                    for item in module.get_module_items():
                                        if hasattr(item, 'title'):
                                            if hasattr(item, 'html_url'):
                                                f.write(item.html_url + '\n')
                                            else:
                                                f.write(item.title + '\n')
                    else:
                        await ctx.send(f'This channel is already tracking {course.name}.')
                else:   # this is the case where args[0] is 'disable'
                    deleted = await self.delete_channel_from_file(ctx.channel, watchers_file)
                    
                    if os.stat(watchers_file).st_size == 0:
                        shutil.rmtree(f'{periodic_tasks.COURSES_DIRECTORY}/{args[1]}')
                    if deleted:
                        await ctx.send(f'This channel is no longer tracking {course.name}.')
                    else:
                        await ctx.send(f'This channel is already not tracking {course.name}.')
            except canvasapi.exceptions.ResourceDoesNotExist:
                await ctx.send("The given course could not be found.")
            except canvasapi.exceptions.Unauthorized:
                await ctx.send("Unauthorized request.")
            except Exception:
                await ctx.send(f'```\n{traceback.format_exc()}\n```')
    
    @commands.command(hidden=True)
    async def update_courses(self, ctx):
        """
        Download and store the latest Canvas modules for all courses being tracked.

        `!update_courses`
        """
        await periodic_tasks.check_canvas(self.bot)
        await ctx.send("Courses updated!")

    async def store_channel_in_file(self, channel, file_path):
        """
        Adds given text channel's id to file with given path (as str) if the channel id is 
        not already contained in the file. Returns True if the channel id was added to the file. 
        Returns False if the channel id was already contained in the file.
        """

        util.create_file_if_not_exists(file_path)

        with open(file_path, "a+") as f:
            # Start reading from the beginning of the file. Note: file *writes*
            # will happen at the end of the file no matter what.
            f.seek(0)

            # The \n has to be here because:
            # - the lines in the file include the \n character at the end
            # - f.write(str) does not insert a new line after writing
            id_to_add = str(channel.id) + "\n"

            for channel_id in f:
                if channel_id == id_to_add:
                    return False

            f.write(id_to_add)

        return True

    async def delete_channel_from_file(self, channel, file_path):
        """
        Removes given text channel's id from file with given path (as str) if the channel id
        is contained in the file. Returns True if the channel id was deleted to the file. 
        Returns False if the channel id could not be found in the file.
        """

        util.create_file_if_not_exists(file_path)

        with open(file_path, "r") as f:
            channel_ids = f.readlines()

        id_to_remove = str(channel.id) + "\n"
        id_found = False

        with open(file_path, "w") as f:
            for channel_id in channel_ids:
                if channel_id != id_to_remove:
                    f.write(channel_id)
                else:
                    id_found = True

        return id_found

# Required function for any extension

def setup(bot):
    bot.add_cog(Main(bot))
    print("Loaded Main cog", flush=True)
    bot.add_cog(Bot_Management(bot))
    print("Loaded Bot_Management cog", flush=True)
