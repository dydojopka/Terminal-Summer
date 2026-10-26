"""Структурные границы DSL, общие для runtime и статической проверки."""

import re


OPTION_RE = re.compile(r'"(.+?)"(?:\s+if\s+(.+))?')


def read_block_range(lines, start: int) -> tuple[int, int]:
    if start >= len(lines) or lines[start] != "{":
        raise ValueError("Expected `{` after block command")
    depth = 1
    for pc in range(start + 1, len(lines)):
        if lines[pc] == "{":
            depth += 1
        elif lines[pc] == "}":
            depth -= 1
            if depth == 0:
                return start + 1, pc
    raise ValueError("Unclosed script block")


def structure_errors(lines) -> list[tuple[int, str]]:
    errors = []

    def sequence(start, end):
        pc = start
        while pc < end:
            line = lines[pc]
            if line.startswith(("if ", "if(")) or line in ("menu", "menu:", "rollcredits"):
                try:
                    body, close = read_block_range(lines, pc + 1)
                    if close >= end:
                        raise ValueError("Block crosses its enclosing boundary")
                    if line in ("menu", "menu:"):
                        cursor = body
                        if cursor == close:
                            raise ValueError("Menu has no options")
                        while cursor < close:
                            if OPTION_RE.fullmatch(lines[cursor]) is None:
                                raise ValueError(f"Invalid menu option: {lines[cursor]}")
                            option, option_end = read_block_range(lines, cursor + 1)
                            if option_end >= close:
                                raise ValueError("Menu option crosses its enclosing boundary")
                            sequence(option, option_end)
                            cursor = option_end + 1
                    else:
                        sequence(body, close)
                    pc = close + 1
                    if line.startswith(("if ", "if(")):
                        while pc < end and (lines[pc] == "else" or lines[pc].startswith("else if ")):
                            is_else = lines[pc] == "else"
                            body, close = read_block_range(lines, pc + 1)
                            if close >= end:
                                raise ValueError("Conditional crosses its enclosing boundary")
                            sequence(body, close)
                            pc = close + 1
                            if is_else:
                                break
                    continue
                except ValueError as exc:
                    errors.append((pc, str(exc)))
            elif line in ("{", "}", "else") or line.startswith("else if"):
                errors.append((pc, f"Unexpected structural command: {line}"))
            elif (option := OPTION_RE.fullmatch(line)) and option[2] is not None:
                errors.append((pc, "Conditional menu option outside a menu"))
            pc += 1

    sequence(0, len(lines))
    return errors
