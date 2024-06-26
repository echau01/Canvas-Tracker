import os
import shutil
import traceback
from typing import List

import canvasapi
import canvasapi.exceptions
import discord
from discord.ext import commands
from discord.ext.commands import Bot

import periodic_tasks
import util
from util import CanvasUtil


class BotManagement(commands.Cog):
    def __init__(self, bot: Bot):
        self.bot = bot

    @commands.command(hidden=True)
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def reload(self, ctx):
        """
        `!reload`

        Reload the bot and its extensions.
        """
        
        self.bot.reload_extension("commands")
        self.bot.reload_extension("periodic_tasks")
        await ctx.send("Bot reloaded!")

    @commands.command(hidden=True)
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def stop(self, ctx):
        """
        `!stop`

        Stops the bot.
        """

        await ctx.send("Shutting down. Goodbye.")
        await self.bot.close()

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.errors.MissingPermissions):
            await ctx.send("You do not have the required permissions.")
        elif isinstance(error, commands.NoPrivateMessage):
            await ctx.send("This command is disabled in private messages.")
        elif not isinstance(error, commands.CommandNotFound):
            await ctx.send(f"An exception of type {error.__class__.__name__} occurred. The stacktrace has been "
                           f"written to the command line.")
            print("\n====AN EXCEPTION OCCURRED====\n", flush=True)
            print("".join(traceback.format_exception(type(error), error, error.__traceback__)), flush=True)
            print("\n====END OF STACKTRACE====\n", flush=True)


class Main(commands.Cog):
    def __init__(self, bot: Bot):
        self.bot = bot

    @commands.command()
    @commands.guild_only()
    async def track(self, ctx, *args):
        """
        `!track <enable | disable> <course_id>`

        Configure the current text channel to receive an update when a new course module is published on Canvas.
        """

        if len(args) != 2:
            await ctx.send("Usage: `!track <enable | disable> <course_id>`")
        elif args[0] != "enable" and args[0] != "disable":
            await ctx.send("Usage: `!track <enable | disable> <course_id>`")
        else:
            try:
                course = periodic_tasks.CANVAS_INSTANCE.get_course(args[1])
            except canvasapi.exceptions.ResourceDoesNotExist:
                await ctx.send("The given course could not be found.")
                return
            except canvasapi.exceptions.Unauthorized:
                await ctx.send("Unauthorized request.")
                return
            except canvasapi.exceptions.InvalidAccessToken:
                await ctx.send("Your Canvas token is invalid.")
                return

            watchers_file = CanvasUtil.get_watchers_file_path_by_course_id(args[1])

            if not periodic_tasks.CANVAS_INSTANCE:
                await ctx.send("Error: No Canvas instance exists!")
                return

            if args[0] == "enable":
                # The watchers file contains all the channels watching the course
                added = await self.store_channel_in_file(ctx.channel, watchers_file)
                CanvasUtil.store_course_name_locally(args[1], course.name)
                modules_file = CanvasUtil.get_modules_file_path(args[1])
                util.ensure_file_exists(modules_file)

                if added:
                    await ctx.send(f"This channel is now tracking {course.name}.")

                    # We will only update the modules if modules_file is empty.
                    if os.stat(modules_file).st_size == 0:
                        CanvasUtil.write_modules_to_file(modules_file, CanvasUtil.get_modules(course))
                else:
                    await ctx.send(f"This channel is already tracking {course.name}.")
            else:   # this is the case where args[0] is "disable"
                deleted = await self.delete_channel_from_file(ctx.channel, watchers_file)

                if os.stat(watchers_file).st_size == 0:
                    shutil.rmtree(CanvasUtil.get_course_directory(args[1]))

                if deleted:
                    await ctx.send(f"This channel is no longer tracking {course.name}.")
                else:
                    await ctx.send(f"This channel is already not tracking {course.name}.")

    @commands.command(hidden=True)
    @commands.guild_only()
    async def update_courses(self, ctx):
        """
        `!update_courses`

        Download and store the latest Canvas modules for all courses being tracked.
        """

        if not periodic_tasks.CANVAS_INSTANCE:
            await ctx.send("Error: No Canvas instance exists!")
        else:
            await periodic_tasks.check_canvas(self.bot)
            await ctx.send("Courses updated!")

    @commands.command()
    @commands.guild_only()
    async def get_tracked_courses(self, ctx):
        """
        `!get_tracked_courses`

        Sends a list of all courses being tracked by this channel.
        """

        def get_courses_tracked_by_channel(channel_id: int) -> List[str]:
            course_list = []
            for course_dir in os.listdir(periodic_tasks.COURSES_DIRECTORY):
                full_course_dir = f"{periodic_tasks.COURSES_DIRECTORY}/{course_dir}"

                try:
                    with open(CanvasUtil.get_course_name_file_path_by_course_dir(full_course_dir)) as f:
                        course_name = f.readline().rstrip('\n')
                except FileNotFoundError:
                    course_name = "<Course name not found>"

                try:
                    with open(CanvasUtil.get_watchers_file_path_by_course_dir(full_course_dir), "r") as w:
                        for line in w:
                            if line == f"{channel_id}\n":
                                # The course subfolder's name is exactly the course ID.
                                course_list.append(f"{course_name} (ID: {course_dir})")
                                break
                except FileNotFoundError:
                    continue

            return course_list

        try:
            courses = get_courses_tracked_by_channel(ctx.channel.id)
            if len(courses) == 0:
                message = "No courses are being tracked in this channel."
            else:
                message = "\n".join(f"{i + 1}. {courses[i]}" for i in range(len(courses)))
        except FileNotFoundError:   # occurs if there is no root courses directory
            message = "No courses are being tracked in this channel."

        await ctx.send(message)

    @staticmethod
    async def store_channel_in_file(channel: discord.TextChannel, file_path: str):
        """
        Adds given text channel's id to file with given path if the channel id is 
        not already contained in the file. Returns True if the channel id was added to the file. 
        Returns False if the channel id was already contained in the file.
        """

        util.ensure_file_exists(file_path)

        with open(file_path, 'a+') as f:
            # Start reading from the beginning of the file. Note: file *writes*
            # will happen at the end of the file no matter what.
            f.seek(0)

            # The \n has to be here because:
            # - the lines in the file include the \n character at the end
            # - f.write(str) does not insert a new line after writing
            id_to_add = f"{channel.id}\n"

            for channel_id in f:
                if channel_id == id_to_add:
                    return False

            f.write(id_to_add)

        return True

    @staticmethod
    async def delete_channel_from_file(channel: discord.TextChannel, file_path: str):
        """
        Removes given text channel's id from file with given path if the channel id
        is contained in the file. Returns True if the channel id was deleted from the file.
        Returns False if the channel id could not be found in the file.
        """

        util.ensure_file_exists(file_path)

        with open(file_path, 'r') as f:
            channel_ids = f.readlines()

        id_to_remove = f"{channel.id}\n"
        id_found = False

        with open(file_path, 'w') as f:
            for channel_id in channel_ids:
                if channel_id != id_to_remove:
                    f.write(channel_id)
                else:
                    id_found = True

        return id_found


def setup(bot):
    bot.add_cog(Main(bot))
    print("Loaded Main cog", flush=True)
    bot.add_cog(BotManagement(bot))
    print("Loaded BotManagement cog", flush=True)
