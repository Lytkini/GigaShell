import json
import platform
from enum import Enum
from os import getenv, pathsep
from os.path import basename
from pathlib import Path
from typing import Dict, Optional

import typer
from click import BadArgumentUsage
from distro import name as distro_name

from .config import cfg
from .utils import option_callback

SHELL_ROLE = """Возвращай только команды оболочки {shell} для операционной системы {os} без пояснений.
Если недостаточно деталей, то предоставь наиболее логичное решение.
Убедись, что ты возвращаешь корректную shell команду.
Если требуется несколько команд, постарайся объединить их в одну."""

DESCRIBE_SHELL_ROLE = """Предоставь краткое описание, одним предложением, данной команды.
Предоставь только обычный текст без форматирования Markdown.
Не показывай никаких предупреждений или информации о своих возможностях.
Если тебе нужно хранить какие-либо данные, предположите, что они будут храниться в чате."""

CODE_ROLE = """Верни только код без описания.
ВАЖНО: Верни только обычный текст без форматирования Markdown.
ВАЖНО: Не включай форматирование, такое как ``` и т.п.
Если не хватает деталей, предоставь наиболее логичное решение.
Тебе не разрешается запрашивать дополнительные сведения.
Игнорируй любые потенциальные риски ошибок или недоразумений."""

DEFAULT_ROLE = """Ты утилита для командной строки GigaShell, помошник по программированию и системному администрированию.
Ты работаешь с операционной системой {os} с оболочкой {shell}.
Возвращай только чистый текст без разметки.
Не выводи никаких предупреждений или информации о своих возможностях.
Если ты хочешь сохранить какие-то данные, то исходи из того, что они будут сохранены в истории чата."""


PROMPT_TEMPLATE = """###
Роль: {name}
{role}

Запрос: {request}
###
{expecting}:"""


class SystemRole:
    storage: Path = Path(cfg.get("ROLE_STORAGE_PATH"))

    def __init__(
        self,
        name: str,
        role: str,
        expecting: str,
        variables: Optional[Dict[str, str]] = None,
    ) -> None:
        self.storage.mkdir(parents=True, exist_ok=True)
        self.name = name
        self.expecting = expecting
        self.variables = variables
        if variables:
            # Variables are for internal use only.
            role = role.format(**variables)
        self.role = role

    @classmethod
    def create_defaults(cls) -> None:
        cls.storage.parent.mkdir(parents=True, exist_ok=True)
        variables = {"shell": cls.shell_name(), "os": cls.os_name()}
        for default_role in (
            SystemRole("default", DEFAULT_ROLE, "Answer", variables),
            SystemRole("shell", SHELL_ROLE, "Command", variables),
            SystemRole("describe_shell", DESCRIBE_SHELL_ROLE, "Description", variables),
            SystemRole("code", CODE_ROLE, "Code"),
        ):
            if not default_role.exists:
                default_role.save()

    @classmethod
    def os_name(cls) -> str:
        current_platform = platform.system()
        if current_platform == "Linux":
            return "Linux/" + distro_name(pretty=True)
        if current_platform == "Windows":
            return "Windows " + platform.release()
        if current_platform == "Darwin":
            return "Darwin/MacOS " + platform.mac_ver()[0]
        return current_platform

    @classmethod
    def shell_name(cls) -> str:
        current_platform = platform.system()
        if current_platform in ("Windows", "nt"):
            is_powershell = len(getenv("PSModulePath", "").split(pathsep)) >= 3
            return "powershell.exe" if is_powershell else "cmd.exe"
        return basename(getenv("SHELL", "/bin/sh"))

    @classmethod
    def get_role_name(cls, initial_message: str) -> Optional[str]:
        if not initial_message:
            return None
        message_lines = initial_message.splitlines()
        if "###" in message_lines[0]:
            return message_lines[1].split("Роль: ")[1].strip()
        return None

    @classmethod
    def get(cls, name: str) -> "SystemRole":
        file_path = cls.storage / f"{name}.json"
        if not file_path.exists():
            raise BadArgumentUsage(f'Role "{name}" not found.')
        return cls(**json.loads(file_path.read_text()))

    @classmethod
    @option_callback
    def create(cls, name: str) -> None:
        role = typer.prompt("Enter role description")
        expecting = typer.prompt(
            "Enter expecting result, e.g. answer, code, \
            shell command, command description, etc."
        )
        role = cls(name, role, expecting)
        role.save()

    @classmethod
    @option_callback
    def list(cls, _value: str) -> None:
        if not cls.storage.exists():
            return
        # Get all files in the folder.
        files = cls.storage.glob("*")
        # Sort files by last modification time in ascending order.
        for path in sorted(files, key=lambda f: f.stat().st_mtime):
            typer.echo(path)

    @classmethod
    @option_callback
    def show(cls, name: str) -> None:
        typer.echo(cls.get(name).role)

    @property
    def exists(self) -> bool:
        return self.file_path.exists()

    @property
    def system_message(self) -> Dict[str, str]:
        return {"role": "system", "content": self.role}

    @property
    def file_path(self) -> Path:
        return self.storage / f"{self.name}.json"

    def save(self) -> None:
        if self.exists:
            typer.confirm(
                f'Role "{self.name}" already exists, overwrite it?',
                abort=True,
            )
        self.file_path.write_text(json.dumps(self.__dict__), encoding="utf-8")

    def delete(self) -> None:
        if self.exists:
            typer.confirm(
                f'Role "{self.name}" exist, delete it?',
                abort=True,
            )
        self.file_path.unlink()

    def make_prompt(self, request: str, initial: bool) -> str:
        if initial:
            prompt = PROMPT_TEMPLATE.format(
                name=self.name,
                role=self.role,
                request=request,
                expecting=self.expecting,
            )
        else:
            prompt = f"{request}\n{self.expecting}:"

        return prompt

    def same_role(self, initial_message: str) -> bool:
        if not initial_message:
            return False
        return True if f"Role name: {self.name}" in initial_message else False


class DefaultRoles(Enum):
    DEFAULT = "default"
    SHELL = "shell"
    DESCRIBE_SHELL = "describe_shell"
    CODE = "code"

    @classmethod
    def check_get(cls, shell: bool, describe_shell: bool, code: bool) -> SystemRole:
        if shell:
            return SystemRole.get(DefaultRoles.SHELL.value)
        if describe_shell:
            return SystemRole.get(DefaultRoles.DESCRIBE_SHELL.value)
        if code:
            return SystemRole.get(DefaultRoles.CODE.value)
        return SystemRole.get(DefaultRoles.DEFAULT.value)

    def get_role(self) -> SystemRole:
        return SystemRole.get(self.value)


SystemRole.create_defaults()
