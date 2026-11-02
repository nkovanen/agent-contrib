"""The installed --help is the documented command surface: every command and option says what it does."""
import argparse
import contextlib
import io
import json
import unittest
from unittest.mock import patch

from agent_contribute import cli, core


def built_parser():
    captured = []

    def capture(parser, *args, **kwargs):
        captured.append(parser)
        raise core.ProtocolError('usage', 'captured')
    with patch.object(cli.Parser, 'parse_args', capture), contextlib.redirect_stdout(io.StringIO()):
        cli.main([])
    return captured[0]


class HelpTests(unittest.TestCase):
    def test_every_subcommand_and_option_has_help(self):
        missing, commands = [], []

        def walk(parser, path):
            for action in parser._actions:
                if isinstance(action, argparse._SubParsersAction):
                    helps = {choice.dest: choice.help for choice in action._choices_actions}
                    for name, sub in action.choices.items():
                        commands.append(' '.join(path + [name]))
                        if not helps.get(name):
                            missing.append(' '.join(path + [name]))
                        walk(sub, path + [name])
                elif not action.help:
                    missing.append(' '.join(path + [action.option_strings[0] if action.option_strings else action.dest]))
        walk(built_parser(), [])
        self.assertIn('evidence init', commands)
        self.assertEqual(len(commands), 14)
        self.assertEqual(missing, [])

    def test_top_level_help_lists_described_commands_and_exit_status(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit) as raised:
            cli.main(['--help'])
        self.assertEqual(raised.exception.code, 0)
        text = output.getvalue()
        self.assertNotIn('(JSON output)', text)
        self.assertIn('Exit status:', text)
        for command in ('discover', 'verify', 'scope-check', 'pr-body'):
            line = next(item for item in text.splitlines() if item.strip().startswith(command + ' '))
            self.assertGreater(len(line.split(None, 1)[1]), 10, line)


class GlobalOptionPlacementTests(unittest.TestCase):
    def invoke(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = cli.main(list(args))
        return code, json.loads(output.getvalue())

    def test_global_option_after_subcommand_names_the_fix(self):
        hint = ('global options --format, --report-budget and --min-remaining go before the subcommand, '
                'for example: agent-contrib --format text verify task.json')
        for args in [('discover', 'acme/photos', '--format', 'text'), ('verify', 'task.json', '--format=text'),
                     ('discover', 'acme/photos', '--report-budget'), ('drift', 'task.json', '--min-remaining', '5')]:
            with self.subTest(args=args):
                code, result = self.invoke(*args)
                self.assertEqual(code, 2)
                self.assertEqual(result['error']['code'], 'usage')
                self.assertTrue(result['error']['message'].startswith('unrecognized arguments: '), result)
                self.assertTrue(result['error']['message'].endswith('; ' + hint), result)
        code, result = self.invoke('discover', 'acme/photos', '--formatting')
        self.assertEqual((code, result['error']['message']), (2, 'unrecognized arguments: --formatting'))


if __name__ == '__main__':
    unittest.main()
