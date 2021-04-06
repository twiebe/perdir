import asyncio
import os
import signal
import sys
from argparse import ArgumentParser, RawDescriptionHelpFormatter
from asyncio.subprocess import STDOUT
from pathlib import Path
from progressbar import ProgressBar
from tempfile import TemporaryFile
from termcolor import cprint, colored
from typing import Union

DESCRIPTION = '''Perdir. Execute a command in a set of paths and show its output.

Command can either be given as raw arguments or as a shell command when encapsulated in quotes. 
Exit code is 0 if all commands were successful or 1 if one or more failed. 
'''
PARALLELISM_ALL = 'all'
PARALLELISM_ENVVAR_NAME = 'PERDIR_PARALLEL'
COLOR_GREEN = 'green'
COLOR_RED = 'red'


class SignalHandler:
    def handle(self, _signum=None, _frame=None):
        cprint("Interrupt received. Aborting.", color='red')
        sys.exit(1)


class DummyProgressbar:
    def __init__(self, *a, **kw):
        return

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return

    def update(self, *a, **kw):
        return


class ParallelismArgumentType:
    def __call__(self, value):
        if value.isdigit():
            return int(value)
        elif value == 'all':
            return value
        else:
            raise ValueError()

    def __repr__(self):
        return 'parallelism'


class ExecuteCommand:
    def __init__(self, path: Path, command: Union[str, list], failed_output_only: bool, semaphore: asyncio.Semaphore,
                 print_lock: asyncio.Lock):
        self._path = path
        self._command = command
        self._failed_output_only = failed_output_only
        self._semaphore = semaphore
        self._print_lock = print_lock
        self._output = None
        self._exit_code = None
        self._success = None

    async def do(self):
        async with self._semaphore:
            if self._is_shell_command():
                await self._execute_command_w_shell()
            else:
                await self._execute_command_wo_shell()
            self._determine_success()
            self._print_result()
            return self._success

    def _is_shell_command(self):
        return len(self._command) == 1

    async def _execute_command_w_shell(self):
        with TemporaryFile() as temporary_file:
            proc = await asyncio.create_subprocess_shell(
                self._command[0],
                cwd=self._path.absolute(),
                stdout=temporary_file,
                stderr=STDOUT,
                close_fds=True)
            self._exit_code = await proc.wait()
            temporary_file.seek(0)
            self._output = temporary_file.read().decode('utf8', errors='replace')

    async def _execute_command_wo_shell(self):
        with TemporaryFile() as temporary_file:
            proc = await asyncio.create_subprocess_exec(
                *self._command,
                cwd=self._path.absolute(),
                stdout=temporary_file,
                stderr=STDOUT,
                close_fds=True)
            self._exit_code = await proc.wait()
            temporary_file.seek(0)
            self._output = temporary_file.read().decode('utf8', errors='replace')

    def _determine_success(self):
        self._success = self._exit_code == 0

    def _print_result(self):
        if self._success:
            headline = colored(f'>> {self._path}', color='green')
            if self._failed_output_only:
                print(f"{headline}")
            else:
                print(f"{headline}{os.linesep}{self._output.rstrip()}{os.linesep}")
        else:
            headline = colored(f'>> {self._path} ({self._exit_code})', color='red')
            print(f"{headline}{os.linesep}{self._output.rstrip()}{os.linesep}")
        sys.stdout.flush()


def split_argv():
    """
    We use -- as a separator between paths and args. argparse also interprets -- to consider
    all following arguments positional, thereby stripping the -- arg.

    Add an additional positional arg to mark the -- spot for later interpretation.
    """
    try:
        separator_index = sys.argv.index('--')
    except ValueError:
        sys_argv = sys.argv[1:]
        cmd_argv = []
    else:
        sys_argv = sys.argv[1:separator_index]
        cmd_argv = sys.argv[separator_index + 1:]
    return sys_argv, cmd_argv


async def main():
    parser = ArgumentParser(description=DESCRIPTION, formatter_class=RawDescriptionHelpFormatter)
    parser.add_argument(
        '-p',
        '--parallel',
        dest='parallel',
        type=ParallelismArgumentType(),
        default=os.getenv(PARALLELISM_ENVVAR_NAME, '1'),
        help=f'Amount of commands to execute in parallel - can also be "all". If not given, env '
             f'var {PARALLELISM_ENVVAR_NAME} is consulted for default. If not set, 1 is used.')
    parser.add_argument(
        '-b',
        '--no-progress',
        dest='progressbar',
        action='store_false',
        default=sys.stdout.isatty(),
        help='Do not show progress.')
    parser.add_argument(
        '-f',
        '--failed-only',
        dest='failed_output_only',
        default=False,
        action='store_true',
        help='Do not show output for successful commands.')
    parser.add_argument(
        dest='paths',
        metavar='path',
        type=Path,
        nargs='*',
        default=[],
        help='List of paths to execute command in')
    parser.usage = f'{parser.format_usage().rstrip()} -- (<args> | "<shell command>")'

    sys_argv, cmd_argv = split_argv()
    args = parser.parse_args(sys_argv)

    if not cmd_argv:
        parser.error('No command given')

    worker_count = len(args.paths) if args.parallel == PARALLELISM_ALL else args.parallel

    signal_handler = SignalHandler()
    signal.signal(signal.SIGINT, signal_handler.handle)
    signal.signal(signal.SIGTERM, signal_handler.handle)

    paths = [path for path in args.paths if path.is_dir()]

    loop = asyncio.get_event_loop()
    semaphore = asyncio.Semaphore(worker_count)
    print_lock = asyncio.Lock()
    tasks = []
    for path in paths:
        command = ExecuteCommand(
            path,
            cmd_argv,
            args.failed_output_only,
            semaphore,
            print_lock)
        task = loop.create_task(command.do(), name=path)
        tasks.append(task)
    tasks_failed = False
    if tasks:
        progressbar_cls = ProgressBar if args.progressbar else DummyProgressbar
        with progressbar_cls(max_value=len(tasks), redirect_stdout=True) as progressbar:
            progressbar.update(0)
            for i, task in enumerate(asyncio.as_completed(tasks), 1):
                success = await task
                progressbar.update(i, force=True)  # w/o force=True, progress is lagging behind.
                if not success:
                    tasks_failed = True
    return 1 if tasks_failed else 0


def entrypoint():
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
