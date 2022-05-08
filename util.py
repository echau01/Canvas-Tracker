import pathlib
import periodic_tasks
import os
from typing import List, Union

from canvasapi.course import Course
from canvasapi.module import Module, ModuleItem


def create_file_if_not_exists(file_path):
    """
    Creates file with given path (as str) if the file does not already exist.
    All required directories are created, too.
    """
    
    pathlib.Path(os.path.dirname(file_path)).mkdir(parents=True, exist_ok=True)

    with open(file_path, 'a'):
        pass


class CanvasUtil:
    @staticmethod
    def get_modules(course: Course) -> List[Union[Module, ModuleItem]]:
        """
        Returns a list of all modules for the given course.
        """

        all_modules = []

        for module in course.get_modules():
            all_modules.append(module)

            for item in module.get_module_items():
                all_modules.append(item)

        return all_modules

    @staticmethod
    def write_modules_to_file(file_path: str, modules: List[Union[Module, ModuleItem]]):
        """
        Stores the IDs of all modules in file with given path.
        """

        with open(file_path, 'w') as f:
            for module in modules:
                f.write(f"{module.id}\n")

    @staticmethod
    def get_course_directory(course_id: str, course_name: str):
        return f"{periodic_tasks.COURSES_DIRECTORY}/{course_id} ({course_name})"
