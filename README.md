# Canvas-Tracker

![Screenshot of Discord message sent by the bot](https://user-images.githubusercontent.com/25561432/96385907-cd543780-114b-11eb-88a9-21c4c406d755.PNG)

In this world of online learning, keeping track of everything that happens in all of your online courses is difficult. This Discord bot serves
to reduce the time you spend checking for course updates by notifying you whenever a new course module is published on Canvas.

This bot is built in Python using [discord.py](https://discordpy.readthedocs.io/en/latest/) and [CanvasAPI](https://canvasapi.readthedocs.io/en/stable/).

## Installation

Clone/fork this repository and install the required libraries using ```pip install -r requirements.txt```. 
Create a file called ```.env``` and add the following lines (replacing the bracketed statements
with actual tokens):

```
DISCORD_TOKEN = {your bot's Discord token}
CANVAS_TOKEN = {your Canvas user token}
```

If you are not a UBC student, you will also need to change the ```CANVAS_URL``` variable in ```periodic_tasks.py``` to the
base Canvas URL of your institution.

Run the bot using ```python main.py```.

## Commands

- ```!track enable <course_id>``` causes the bot to track Canvas modules for the given course. When a new module is published
in that course, the bot will notify you in the Discord channel where the command was typed.
    - Note: this bot only watches for new modules. The bot does *not* track updates to content within course modules, 
    so you will not receive a notification if the content in an existing course module is changed.
- ```!track disable <course_id>``` stops tracking a Canvas course in the Discord channel where the command was typed.
- ```!get_tracked_courses``` sends a list of courses being tracked by the current channel.
- ```!reload``` reloads the bot. The bot will also check Canvas for new modules upon reloading. This command requires administrator permissions.
- ```!stop``` stops the bot. This command requires administrator permissions.
- ```!update_courses``` downloads and stores the latest Canvas modules for all courses being tracked.
