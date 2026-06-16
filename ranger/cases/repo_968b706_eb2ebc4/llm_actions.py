# This file is part of ranger, the console file manager.
# License: GNU GPL version 3, see the file "AUTHORS" for details.

# pylint: disable=too-many-lines,attribute-defined-outside-init

from __future__ import (absolute_import, division, print_function)

import codecs
import os
import re
import shlex
import shutil
import string
import tempfile
from hashlib import sha512
from inspect import cleandoc
from io import open
from logging import getLogger
from os import link, symlink, listdir, stat
from os.path import join, isdir, realpath, exists
from stat import S_IEXEC

import ranger
from ranger import PY3
from ranger.container.directory import Directory
from ranger.container.file import File
from ranger.container.settings import ALLOWED_SETTINGS, ALLOWED_VALUES
from ranger.core.loader import CommandLoader, CopyLoader
from ranger.core.shared import FileManagerAware, SettingsAware
from ranger.core.tab import Tab
from ranger.ext.direction import Direction
from ranger.ext.get_executables import get_executables
from ranger.ext.keybinding_parser import key_to_string, construct_keybinding
from ranger.ext.macrodict import MacroDict, MACRO_FAIL, macro_val
from ranger.ext.relative_symlink import relative_symlink
from ranger.ext.rifle import squash_flags, ASK_COMMAND
from ranger.ext.safe_path import get_safe_path
from ranger.ext.shell_escape import shell_quote

LOG = getLogger(__name__)


class _MacroTemplate(string.Template):
    """A template for substituting macros in commands"""
    delimiter = ranger.MACRO_DELIMITER
    idpattern = r"[_a-z0-9]*"


class Actions(  # pylint: disable=too-many-instance-attributes,too-many-public-methods
        FileManagerAware, SettingsAware):

    # --------------------------
    # -- Basic Commands
    # --------------------------

    @staticmethod
    def exit():
        """:exit

        Exit the program.
        """
        raise SystemExit

    def reset(self):
        """:reset

        Reset the filemanager, clearing the directory buffer, reload rifle config
        """
        old_path = self.thisdir.path
        self.previews = {}
        self.garbage_collect(-1)
        self.enter_dir(old_path)
        self.change_mode('normal')
        if self.metadata:
            self.metadata.reset()
        self.rifle.reload_config()
        self.fm.tags.sync()

    def change_mode(self, mode=None):
        """:change_mode <mode>

        Change mode to "visual" (selection) or "normal" mode.
        """
        if mode is None:
            self.fm.notify('Syntax: change_mode <mode>', bad=True)
            return
        if mode == self.mode:  # pylint: disable=access-member-before-definition
            return
        if mode == 'visual':
            self._visual_pos_start = self.thisdir.pointer
            self._visual_move_cycles = 0
            self._previous_selection = set(self.thisdir.marked_items)
            self.mark_files(val=not self._visual_reverse, movedown=False)
        elif mode == 'normal':
            if self.mode == 'visual':  # pylint: disable=access-member-before-definition
                self._visual_pos_start = None
                self._visual_move_cycles = None
                self._previous_selection = None
        else:
            return
        self.mode = mode
        self.ui.status.request_redraw()

    def set_option_from_string(self, option_name, value, localpath=None, tags=None):
        if option_name not in ALLOWED_SETTINGS:
            raise ValueError("The option named `%s' does not exist" % option_name)
        if not isinstance(value, str):
            raise ValueError("The value for an option needs to be a string.")

        self.settings.set(option_name, self._parse_option_value(option_name, value),
                          localpath, tags)

    def _parse_option_value(  # pylint: disable=too-many-return-statements
            self, name, value):
        types = self.fm.settings.types_of(name)
        if bool in types:
            if value.lower() in ('false', 'off', '0'):
                return False
            elif value.lower() in ('true', 'on', '1'):
                return True
        if isinstance(None, types) and value.lower() == 'none':
            return None
        if int in types:
            try:
                return int(value)
            except ValueError:
                pass
        if float in types:
            try:
                return float(value)
            except ValueError:
                pass
        if str in types:
            return value
        if list in types:
            return value.split(',')
        raise ValueError("Invalid value `%s' for option `%s'!" % (value, name))

    def toggle_visual_mode(self, reverse=False, narg=None):
        """:toggle_visual_mode

        Toggle the visual mode (see :change_mode).
        """
        if self.mode == 'normal':
            self._visual_reverse = reverse
            if narg is not None:
                self.mark_files(val=not reverse, narg=narg)
            self.change_mode('visual')
        else:
            self.change_mode('normal')

    def reload_cwd(self):
        """:reload_cwd

        Reload the current working directory.
        """
        try:
            cwd = self.thisdir
        except AttributeError:
            pass
        else:
            cwd.unload()
            cwd.load_content()

    def notify(self, obj, duration=4, bad=False, exception=None):
        """:notify <text>

        Display the text in the statusbar.
        """
        if isinstance(obj, Exception):
            if ranger.args.debug:
                raise obj
            exception = obj
            bad = True
        elif bad and ranger.args.debug:
            class BadNotification(Exception):
                pass
            raise BadNotification(str(obj))

        text = str(obj)

        text_log = 'Notification: {0}'.format(text)
        if bad:
            LOG.error(text_log)
        else:
            LOG.info(text_log)
        if exception:
            LOG.exception(exception)

        if self.ui and self.ui.is_on:
            self.ui.status.notify("  ".join(text.split("\n")),
                                  duration=duration, bad=bad)
        else:
            print(text)

    def abort(self):
        """:abort

        Empty the first queued action.
        """
        try:
            item = self.loader.queue[0]
        except IndexError:
            self.notify("Type Q or :quit<Enter> to exit ranger")
        else:
            self.notify("Aborting: " + item.get_description())
            self.loader.remove(index=0)

    def get_cumulative_size(self):
        for fobj in self.thistab.get_selection() or ():
            fobj.look_up_cumulative_size()
        self.ui.status.request_redraw()
        self.ui.redraw_main_column()

    def redraw_window(self):
        """:redraw_window

        Redraw the window.
        """
        self.ui.redraw_window()

    def open_console(self, string='',  # pylint: disable=redefined-outer-name
                     prompt=None, position=None):
        """:open_console [string]

        Open the console.
        """
        self.change_mode('normal')
        self.ui.open_console(string, prompt=prompt, position=position)

    def execute_console(self, string='',  # pylint: disable=redefined-outer-name
                        wildcards=None, quantifier=None):
        """:execute_console [string]

        Execute a command for the console
        """
        command_name = string.lstrip().split()[0]
        cmd_class = self.commands.get_command(command_name)
        if cmd_class is None:
            self.notify("Command not found: `%s'" % command_name, bad=True)
            return None
        cmd = cmd_class(string, quantifier=quantifier)

        if cmd.resolve_macros and _MacroTemplate.delimiter in cmd.line:
            def any_macro(i, char):
                return ('any{0:d}'.format(i), key_to_string(char))

            def anypath_macro(i, char):
                try:
                    val = self.fm.bookmarks[key_to_string(char)]
                except KeyError:
                    val = MACRO_FAIL
                return ('any_path{0:d}'.format(i), val)

            macros = dict(f(i, char) for f in (any_macro, anypath_macro)
                          for i, char in enumerate(wildcards if wildcards
                                                   is not None else []))
            if 'any0' in macros:
                macros['any'] = macros['any0']
                if 'any_path0' in macros:
                    macros['any_path'] = macros['any_path0']
            try:
                line = self.substitute_macros(cmd.line, additional=macros,
                                              escape=cmd.escape_macros_for_shell)
            except ValueError as ex:
                if ranger.args.debug:
                    raise
                return self.notify(ex)
            cmd.init_line(line)

        try:
            cmd.execute()
        except Exception as ex:  # pylint: disable=broad-except
            if ranger.args.debug:
                raise
            self.notify(ex)
        return None

    def substitute_macros(self, string,  # pylint: disable=redefined-outer-name
                          additional=None, escape=False):
        macros = self.get_macros()
        if additional:
            macros.update(additional)
        if escape:
            for key, value in macros.items():
                if isinstance(value, list):
                    macros[key] = " ".join(shell_quote(s) for s in value)
                elif value != MACRO_FAIL:
                    macros[key] = shell_quote(value)
        else:
            for key, value in macros.items():
                if isinstance(value, list):
                    macros[key] = " ".join(value)
        result = _MacroTemplate(string).safe_substitute(macros)
        if MACRO_FAIL in result:
            raise ValueError("Could not apply macros to `%s'" % string)
        return result

    def get_macros(self):
        macros = MacroDict()

        macros['rangerdir'] = ranger.RANGERDIR
        macros['confdir'] = self.fm.confpath
        macros['datadir'] = self.fm.datapath
        macros['space'] = ' '
        macros['f'] = self.fm.thisfile.relative_path
        macros['p'] = self.fm.thisfile.relative_path
        macros['s'] = [f.relative_path for f in self.fm.thistab.get_selection()]
        macros['c'] = [f.path for f in self.fm.copy_buffer]
        macros['t'] = self.fm.tags.marker(
            self.fm.thisfile.realpath if self.fm.thisfile else None)
        macros['d'] = self.fm.thisdir.path
        macros['cwd'] = self.fm.thisdir.path
        macros['fm'] = self.fm
        macros['files'] = self.fm.thisdir.files
        macros['thisfile'] = self.fm.thisfile
        macros['thisdir'] = self.fm.thisdir
        macros['selection'] = self.fm.thistab.get_selection()

        if self.fm.thisfile:
            macros['file'] = self.fm.thisfile.path
            macros['basename'] = self.fm.thisfile.basename
            macros['ext'] = self.fm.thisfile.extension
            macros['relative_path'] = self.fm.thisfile.relative_path
            macros['filename'] = self.fm.thisfile.relative_path
            macros['dirname'] = self.fm.thisfile.dirname
            macros['path'] = self.fm.thisfile.path

        if self.fm.thisdir:
            macros['directory'] = self.fm.thisdir.path

        # define d/f/p/s macros for each tab
        for i, tabname in enumerate(self.fm.get_tab_list()):
            tab = self.fm.tabs[tabname]
            macros['D' + str(i)] = tab.thisdir.path
            macros['F' + str(i)] = tab.thisfile.path if tab.thisfile else None
            macros['P' + str(i)] = tab.thisfile.relative_path if tab.thisfile else None
            macros['S' + str(i)] = [f.path for f in tab.get_selection()]

        return macros

    def source(self, filename):
        filename = os.path.expanduser(filename)
        if not os.path.exists(filename):
            self.fm.notify("source: File `%s' does not exist!" % filename, bad=True)
            return

        with open(filename, 'r', encoding="utf-8") as fobj:
            lines = fobj.readlines()

        for line in lines:
            if line and line[0] != '#':
                self.execute_console(line)

    def execute_file(self, files, **kw):
        """Uses the rifle class to open/runs files"""
        if 'mode' not in kw:
            kw['mode'] = 0
        if files is None:
            files = [self.fm.thisfile]
        elif isinstance(files, set):
            files = list(files)
        if not files:
            return

        label = kw['label'] if 'label' in kw else None
        flags = kw['flags'] if 'flags' in kw else ''
        mode = kw['mode'] if 'mode' in kw else 0

        # if $PAGER is not set and plain text file is selected, use internal
        # pager by default
        if 'r' not in flags and 'PAGER' not in os.environ:
            for fobj in files:
                if 'text' in self.fm.mimetypes.guess_type(fobj.path)[0]:
                    self.run(shlex.split(ranger.DEFAULT_PAGER) + [fobj.path])
                    return

        self.rifle.execute(files, number=mode, label=label, flags=flags)

    def edit_file(self, file=None):
        """Calls execute_file with the current file and label="editor"."""
        if file is None:
            file = self.fm.thisfile
        self.execute_file(file, label='editor')

    def run(self, command, flags='', **popen_kws):
        """Run a command"""
        if isinstance(command, str):
            command = shlex.split(command)
        if 'f' in flags:
            popen_kws['stdout'] = popen_kws['stderr'] = open(os.devnull, 'w')
        elif 'r' in flags:
            popen_kws['stderr'] = open(os.devnull, 'w')
        elif 't' in flags:
            popen_kws['stdout'] = open(os.devnull, 'w')
        popen_kws['shell'] = 's' in flags
        if 'p' in flags:
            return os.system(command)  # pylint: disable=lost-exception
        else:
            exc = popen_kws.pop("exceptions", None)
            if exc is None:
                exc = (AttributeError, OSError, ValueError)
            try:
                return self.popen_forked(*command, **popen_kws)
            except exc as ex:
                self.fm.notify("Error: " + str(ex), bad=True)
                return None

    def rerun_with_sudo(self):
        if self.fm.settings.sudo_prompt and os.environ.get('SUDO_ASKPASS'):
            flags = 'f'
        else:
            flags = ''
        self.run(['sudo', '-E', 'su'], flags=flags)

    def dump(self):
        """:dump

        Dump keybindings, commands and settings to the console.
        """
        self.dump_keybindings()
        self.dump_commands()
        self.dump_settings()

    @staticmethod
    def get_preview(fileobj, width, height):
        return fileobj.get_preview_source(width, height)

    def display_file(self):
        """Display the current file in the pager"""
        if not self.fm.thisfile:
            return
        if not self.fm.thisfile.is_file:
            return

        self.run(ranger.DEFAULT_PAGER, flags='f', stdin=open(self.fm.thisfile.path, 'r'))

    def scroll_preview(self, lines):
        if self.thisdir:
            self.thisdir.move(invoke=self._draw_directory)

        direction = Direction(
            down=lines,
            pagesize=self.ui.termsize[0],
            cycle=False,
        )
        self.ui.browser.column[-1].scrollbit(direction)

    def _draw_directory(self):
        self.ui.browser.main_column.request_redraw()

    def move(self,  # pylint: disable=too-many-locals,too-many-branches,too-many-statements
             narg=None, **kw):
        """Move to a file, a directory or something else"""
        direction = Direction(kw)
        if direction.move_cycles:
            self._visual_move_cycles += direction.move_cycles

        if self.thisdir is None:
            return False

        if direction.enter_dir and self.thisfile is not None and \
                self.thisfile.is_directory:
            self.enter_dir(self.thisfile.path)
            return True

        if direction.direction == 0:
            self.move_parent(direction)
            return False

        if narg:
            direction. *= narg

        if direction.pages():
            direction.set(
                pagesize=self.ui.browser.hei - 1)

        cwd = self.thisdir
        pointer = cwd.pointer
        maximum = len(cwd) - 1

        if direction.vertical():
            pos_new = direction.move(
                direction=1,
                current=pointer,
                minimum=0,
                maximum=maximum,
                page_size=self.ui.browser.hei)
        else:
            pos_new = direction.move(
                direction=1,
                current=pointer,
                minimum=0,
                maximum=maximum)

        if pos_new != pointer:
            cwd.pointer = pos_new
            cwd.correct_pointer()

            if self.mode == 'visual':
                move_cycles = direction.move_cycles + self._visual_move_cycles
                if pointer in cwd.marked_items:
                    cwd.mark_item(False, cwd.files[pointer])
                elif move_cycles > 0:
                    cwd.mark_item(True, cwd.files[pointer])

                if move_cycles < 0:
                    cwd.mark_item(False, cwd.files[pos_new])
                elif pos_new in self._previous_selection:
                    cwd.mark_item(True, cwd.files[pos_new])

                if cwd.pointer == self._visual_pos_start:
                    cwd.mark_item(
                        self._visual_pos_start in self._previous_selection,
                        cwd.files[self._visual_pos_start])

        self.signal_emit('move', old=pointer, new=cwd.pointer)

        return pointer != cwd.pointer

    def move_parent(self, direction):
        if self.fm.thisdir.parent is not None:
            self.enter_dir(self.fm.thisdir.parent.path)
            self.fm.move(to=self.fm.thisdir.pointer + direction.relative())

    def select_file(self, path):
        path = path.strip()
        if not path:
            return
        dirname, basename = os.path.split(path)
        try:
            cwd = self.fm.env.get_directory(dirname)
        except ValueError:
            return
        cwd.load_content(schedule=False)
        for i, item in enumerate(cwd.files):
            if item.basename == basename:
                cwd.pointer = i
                break
        self.fm.thistab.enter_dir(dirname)
        self.fm.thisdir = cwd

    def history_go(self, relative):
        """Move back and forth in the history"""
        if relative:
            self.thistab.history_go(relative)

    def enter_bookmark(self, key):
        """Enter the bookmark with the given key"""
        try:
            destination = self.bookmarks[str(key)]
        except KeyError:
            self.notify("Bookmark `%s' does not exist" % key, bad=True)
            return
        self.enter_dir(destination)

    def enter_dir(self, path=None, remember=False, history=True):
        """Enter the directory at the given path"""
        if path is None:
            path = '/'
        path = os.path.realpath(path)

        selectfile = None
        if os.path.isfile(path):
            selectfile = path
            path = os.path.dirname(path)

        try:
            cwd = self.fm.get_directory(path)
        except OSError as err:
            self.notify(err)
            return

        if cwd is not None:
            # move pointer before sorting, to maintain pointer position
            if selectfile is None and path == self.thisdir.path:
                try:
                    sort = self.settings['sort']
                except KeyError:
                    pass
                else:
                    if sort == 'random':
                        self.thisdir.refilter()
                        self.thisdir.sort_if_outdated()

            self.thistab.enter_dir(path, remember=remember, history=history)

            if selectfile is not None:
                self.select_file(selectfile)

            self.change_mode('normal')

    def cd(self, path):
        """:cd <path>

        Change the directory to the given path.
        """
        if not path:
            path = '/'
        self.enter_dir(path)

    def traverse(self):
        self.move(down=1)
        while self.thisfile is not None and self.thisfile.is_directory:
            self.enter_dir()
            self.move(right=1)
            self.move(down=1)
            while self.thisfile is not None and self.thisfile.is_link:
                self.move(down=1)

    def search_file(self, text, offset=1, regexp=True):
        """:search_file [text]

        Search all files in the current directory for a case-insensitive match.
        """
        if regexp:
            pattern = re.compile(text, re.IGNORECASE)
            match = lambda x: pattern.search(x.basename)
        else:
            match = lambda x: text.lower() in x.basename.lower()

        cwd = self.thisdir
        lst = list(cwd.files)
        length = len(lst)
        while length:
            cwd.move(to=(cwd.pointer + offset) % len(cwd.files))
            if match(cwd.files[cwd.pointer]):
                return True
            length -= 1
        return False

    def set_search_method(self, order='search'):
        if order in ('search', 'tag'):
            self.search_method = order

    def tag_toggle(self, tag=None, paths=None, value=None):
        """
        Toggle the tag of the selected files.

        Parameters:
        tag: the tag which should be changed, if no value is given,
             the old tag is toggled, otherwise the given value is used.
        value: if True, the tag is set.  If False, the tag is removed.
        """
        if paths is None:
            paths = [f.path for f in self.fm.thistab.get_selection()]

        if tag is None:
            tag = self.tags.default_tag

        self.tags.toggle(*paths, value=value, tag=tag)

    def set_bookmark(self, key, val=None):
        """:set_bookmark <key> [path]

        Assign a bookmark to the given key with the given path.
        """
        if val is None:
            val = self.thisdir.path
        self.bookmarks[str(key)] = val

    def unset_bookmark(self, key):
        """:unset_bookmark <key>

        Remove the bookmark associated with the given key.
        """
        if key in self.bookmarks:
            del self.bookmarks[key]

    def draw_bookmarks(self):
        self.ui.browser.draw_bookmarks = True
        self.ui.redraw_main_column()

    def hide_bookmarks(self):
        self.ui.browser.draw_bookmarks = False
        self.ui.redraw_main_column()

    def draw_possible_programs(self):
        self.ui.browser.draw_hints = True
        self.ui.redraw_main_column()

    def hide_possible_programs(self):
        self.ui.browser.draw_hints = False
        self.ui.redraw_main_column()

    def display_log(self):
        logs = self.log[:]
        logs.reverse()
        self.ui.open_pager()
        lines = []
        for entry in logs:
            lines += entry.split("\n")
        self.ui.pager.set_source(lines)

    def display_help(self):
        self.run("%s/help/ranger" % self.confpath, flags='p')

    def display_version(self):
        self.notify('ranger {0}, executed with python {1}'.format(
            ranger.__version__, re.sub('\n', '', os.popen('python --version 2>&1').read())
        ))

    def move_pager(self, *args, **kw):
        self.ui.get_pager().move(*args, **kw)

    def sort(self, func=None, reverse=None):
        if reverse is not None:
            self.settings['sort_reverse'] = reverse
        if func is not None:
            self.settings['sort'] = func

    def mark_files(self, val, allfiles=False, movedown=None, narg=None):
        cwd = self.thisdir
        if not cwd:
            return

        if movedown is None:
            movedown = not val

        selected = set(cwd.get_selection())

        if allfiles:
            if selected != set(cwd.files):
                selected = set(cwd.files)
            else:
                selected = set()
            cwd.set_marked_items(selected)
            return

        if narg:
            direction = Direction(down=1)
            pos, selected = direction.select(
                override=narg,
                lst=cwd.files,
                current=cwd.pointer,
                pagesize=self.ui.termsize[0])
            cwd.pointer = pos
            cwd.correct_pointer()
        else:
            selected = set(cwd.get_selection())

        if val:
            cwd.mark_all(selected)
        else:
            cwd.unmark_all(selected)

        if movedown:
            cwd.move(down=1)

    def mark_in_direction(self, val=True, dirarg=None):
        cwd = self.thisdir
        direction = Direction(dirarg)
        _, selected = direction.select(
            lst=cwd.files, current=cwd.pointer,
            pagesize=self.ui.termsize[0]
        )
        cwd.pointer = direction.move(
            direction=1,
            current=cwd.pointer,
            minimum=0,
            maximum=len(cwd.files) - 1,
            pagesize=self.ui.termsize[0],
        )
        cwd.correct_pointer()
        if val:
            cwd.mark_all(selected)
        else:
            cwd.unmark_all(selected)

    def search_next(self, order=None):
        if order is not None:
            self.set_search_method(order=order)
        if self.search_method == 'search':
            return self.search_next_order(reverse=False)
        elif self.search_method == 'tag':
            return self.search_next_tag(False)

    def search_previous(self, order=None):
        if order is not None:
            self.set_search_method(order=order)
        if self.search_method == 'search':
            return self.search_next_order(reverse=True)
        elif self.search_method == 'tag':
            return self.search_next_tag(True)

    def search_next_order(self, reverse=False):
        if self.thisdir:
            self.thisdir.search_fnc(
                order=self.search_function,
                offset=-1 if reverse else 1,
                forward=not reverse)

    def search_next_tag(self, backward=False):
        if self.thisdir:
            return self.thisdir.search_fnc(
                order='tag',
                offset=-1 if backward else 1,
                forward=not backward)

    def set_search_method(self, order='search'):
        if order in ('search', 'tag'):
            self.search_method = order

    def pager_move(self, narg=None, **kw):
        self.ui.get_pager().move(narg=narg, **kw)

    def taskview_move(self, narg=None, **kw):
        self.ui.taskview.move(narg=narg, **kw)

    def pause_tasks(self):
        self.loader.pause(-1)

    def pause_after(self, n):
        self.loader.pause(n)

    def close(self):
        self.fm.exit()

    def quit(self):
        self.fm.exit()

    def quit_when_no_tabs(self, narg=1):
        if narg <= 1 and len(self.fm.tabs) > 1:
            self.fm.tab_close()
        else:
            self.fm.exit()

    def close_window(self):
        if self.fm.tabs:
            self.fm.tab_close()
        else:
            self.fm.exit()

    def tab_open(self, name=None):
        self.fm.tab_open(name=name)

    def tab_close(self, name=None):
        self.fm.tab_close(name=name)

    def tab_move(self, offset=1):
        self.fm.tab_move(offset=offset)

    def tab_new(self, path=None):
        self.fm.tab_new(path)

    def tab_restore(self):
        self.fm.tab_restore()

    def tab_switch(self, path=None, create_directory=False):
        """Switches to tab of given path, opening new tab as needed.
        "path" can be a string or a Tab object.

        If path is a Tab or path already exists in tabs, switch to tab.
        Otherwise, open a new tab with this path.
        If create_directory is True, create the directory if necessary.
        """

        file_selection = None

        if isinstance(path, Tab):
            name = path.name
            self.fm.tab_open(name=name)
            return

        if path is None:
            return

        path = os.path.abspath(path)
        target_directory = path
        if not os.path.isdir(target_directory):
            if os.path.exists(target_directory):
                file_selection = target_directory
                target_directory = os.path.dirname(target_directory)
            elif create_directory:
                os.makedirs(target_directory)
            else:
                return

        for name in self.fm.get_tab_list():
            tab = self.fm.tabs[name]
            if os.path.abspath(tab.path) == target_directory:
                self.fm.tab_open(name=name)
                if file_selection:
                    self.fm.select_file(file_selection)
                return

        self.fm.tab_new(path=target_directory)
        if file_selection:
            self.fm.select_file(file_selection)

    def tabswitch(self, *args, **kwargs):
        return self.tab_switch(*args, **kwargs)

    def get_tab_list(self):
        assert self.tabs, "There must be at least 1 tab at all times"

        class NaturalOrder(object):  # pylint: disable=too-few-public-methods
            def __init__(self, obj):
                self.obj = obj

            def __lt__(self, other):
                try:
                    return self.obj < other.obj
                except TypeError:
                    return str(self.obj) < str(other.obj)

        return sorted(self.tabs, key=NaturalOrder)

    # --------------------------
    # -- Overview of internals
    # --------------------------

    def _run_pager(self, path):
        self.run(shlex.split(os.environ.get('PAGER', ranger.DEFAULT_PAGER)) + [path])

    def dump_keybindings(self, *contexts):
        if not contexts:
            contexts = 'browser', 'console', 'pager', 'taskview'

        # Disable lint because TemporaryFiles are removed on close
        # pylint: disable=consider-using-with
        temporary_file = tempfile.NamedTemporaryFile()

        def write(string):  # pylint: disable=redefined-outer-name
            temporary_file.write(string.encode('utf-8'))

        def recurse(before, pointer):
            for key, value in pointer.items():
                keys = before + [key]
                if isinstance(value, dict):
                    recurse(keys, value)
                else:
                    write("%12s %s\n" % (construct_keybinding(keys), value))

        for context in contexts:
            write("Keybindings in `%s'\n" % context)
            if context in self.fm.ui.keymaps:
                recurse([], self.fm.ui.keymaps[context])
            else:
                write("  None\n")
            write("\n")

        temporary_file.flush()
        self._run_pager(temporary_file.name)

    def dump_commands(self):
        # Disable lint because TemporaryFiles are removed on close
        # pylint: disable=consider-using-with
        temporary_file = tempfile.NamedTemporaryFile()

        def write(string):  # pylint: disable=redefined-outer-name
            temporary_file.write(string.encode('utf-8'))

        undocumented = []
        for cmd_name in sorted(self.commands.commands):
            cmd = self.commands.commands[cmd_name]
            if hasattr(cmd, '__doc__') and cmd.__doc__:
                doc = cleandoc(cmd.__doc__)
                if doc[0] == ':':
                    write(doc)
                    write("\n\n" + "-" * 60 + "\n")
            else:
                undocumented.append(cmd)

        if undocumented:
            write("Undocumented commands:\n\n")
            for cmd in undocumented:
                write("    :%s\n" % cmd.get_name())

        temporary_file.flush()
        self._run_pager(temporary_file.name)

    def dump_settings(self):
        # Disable lint because TemporaryFiles are removed on close
        # pylint: disable=consider-using-with
        temporary_file = tempfile.NamedTemporaryFile()

        def write(string):  # pylint: disable=redefined-outer-name
            temporary_file.write(string.encode('utf-8'))

        for setting in sorted(ALLOWED_SETTINGS):
            write("%30s = %s\n" % (setting, getattr(self.settings, setting)))

        temporary_file.flush()
        self._run_pager(temporary_file.name)

    # --------------------------
    # -- File System Operations
    # --------------------------

    def uncut(self):
        """:uncut

        Empty the copy buffer.
        """
        self.copy_buffer = set()
        self.do_cut = False
        self.ui.browser.main_column.request_redraw()

    def copy(self, mode='set', narg=None, dirarg=None):
        """:copy [mode=set]

        Copy the selected items.
        Modes are: 'set', 'add', 'remove'.
        """
        assert mode in ('set', 'add', 'remove', 'toggle')
        cwd = self.thisdir
        if not narg and not dirarg:
            selected = (fobj for fobj in self.thistab.get_selection() if fobj in cwd.files)
        else:
            if not dirarg and narg:
                direction = Direction(down=1)
                offset = 0
            else:
                direction = Direction(dirarg)
                offset = 1
            pos, selected = direction.select(override=narg, lst=cwd.files, current=cwd.pointer,
                                             pagesize=self.ui.termsize[0], offset=offset)
            cwd.pointer = pos
            cwd.correct_pointer()
        if mode == 'set':
            self.copy_buffer = set(selected)
        elif mode == 'add':
            self.copy_buffer.update(set(selected))
        elif mode == 'remove':
            self.copy_buffer.difference_update(set(selected))
        elif mode == 'toggle':
            self.copy_buffer.symmetric_difference_update(set(selected))
        self.do_cut = False
        self.ui.browser.main_column.request_redraw()

    def cut(self, mode='set', narg=None, dirarg=None):
        """:cut [mode=set]

        Cut the selected items.
        Modes are: 'set, 'add, 'remove.
        """
        self.copy(mode=mode, narg=narg, dirarg=dirarg)
        self.do_cut = True
        self.ui.browser.main_column.request_redraw()

    def paste_symlink(self, relative=False, make_safe_path=get_safe_path):
        copied_files = self.copy_buffer
        for fobj in copied_files:
            new_name = make_safe_path(fobj.basename)
            self.notify(new_name)
            try:
                if relative:
                    relative_symlink(fobj.path, join(self.fm.thisdir.path, new_name))
                else:
                    symlink(fobj.path, join(self.fm.thisdir.path, new_name))
            except OSError as ex:
                self.notify('Failed to paste symlink: View log for more info',
                            bad=True, exception=ex)

    def paste_hardlink(self, make_safe_path=get_safe_path):
        for fobj in self.copy_buffer:
            new_name = make_safe_path(fobj.basename)
            try:
                link(fobj.path, join(self.fm.thisdir.path, new_name))
            except OSError as ex:
                self.notify('Failed to paste hardlink: View log for more info',
                            bad=True, exception=ex)

    def paste_hardlinked_subtree(self, make_safe_path=get_safe_path):
        for fobj in self.copy_buffer:
            try:
                target_path = join(self.fm.thisdir.path, fobj.basename)
                self._recurse_hardlinked_tree(fobj.path, target_path, make_safe_path)
            except OSError as ex:
                self.notify('Failed to paste hardlinked subtree: View log for more info',
                            bad=True, exception=ex)

    def _recurse_hardlinked_tree(self, source_path, target_path, make_safe_path):
        if isdir(source_path):
            if not exists(target_path):
                os.mkdir(target_path, stat(source_path).st_mode)
            for item in listdir(source_path):
                self._recurse_hardlinked_tree(
                    join(source_path, item),
                    join(target_path, item),
                    make_safe_path)
        else:
            if not exists(target_path) \
                    or stat(source_path).st_ino != stat(target_path).st_ino:
                link(source_path, make_safe_path(target_path))

    def paste(self, overwrite=False, append=False, dest=None, make_safe_path=get_safe_path):
        """:paste

        Paste the selected items into the current directory or to dest
        if provided.
        """
        if dest is None:
            dest = self.thistab.path
        if isdir(dest):
            loadable = CopyLoader(
                self.copy_buffer,
                do_cut=self.do_cut,
                overwrite=overwrite,
                dest=dest,
                make_safe_path=make_safe_path,
            )
            self.loader.add(loadable, append=append)
            self.do_cut = False
        else:
            self.notify('Failed to paste. The destination is invalid.', bad=True)

    def delete(self, files=None):
        # XXX: warn when deleting mount points/unseen marked files?
        # COMPAT: old command.py use fm.delete() without arguments
        if files is None:
            files = (fobj.path for fobj in self.thistab.get_selection())
        self.notify("Deleting {fls}!".format(fls=", ".join(files)))
        files = [os.path.abspath(path) for path in files]
        for path in files:
            # Untag the deleted files.
            for tag in self.fm.tags.tags:
                if str(tag).startswith(path):
                    self.fm.tags.remove(tag)
        self.copy_buffer = set(fobj for fobj in self.copy_buffer if fobj.path not in files)
        for path in files:
            if isdir(path) and not os.path.islink(path):
                try:
                    shutil.rmtree(path)
                except OSError as err:
                    self.notify(err)
            else:
                try:
                    os.remove(path)
                except OSError as err:
                    self.notify(err)
        self.thistab.ensure_correct_pointer()

    def mkdir(self, name):
        try:
            os.makedirs(os.path.join(self.thisdir.path, name))
        except OSError as err:
            self.notify(err)

    def rename(self, src, dest):
        if hasattr(src, 'path'):
            src = src.path

        try:
            os.makedirs(os.path.dirname(dest))
        except OSError:
            pass
        try:
            os.rename(src, dest)
        except OSError as err:
            self.notify(err)
            return False
        return True