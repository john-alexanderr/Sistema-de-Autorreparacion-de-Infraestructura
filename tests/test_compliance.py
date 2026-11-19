"""AST guards for the course error-handling and cleanup rules."""

import ast
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOTS = (PROJECT_ROOT / "src", PROJECT_ROOT / "tests")


def _project_python_files() -> list[Path]:
    return sorted(
        path
        for root in PYTHON_ROOTS
        for path in root.rglob("*.py")
        if path.is_file()
    )


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _bare_except_pass_handlers(tree: ast.Module) -> list[ast.ExceptHandler]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ExceptHandler)
        and node.type is None
        and len(node.body) == 1
        and isinstance(node.body[0], ast.Pass)
    ]


def _exception_aliases(tree: ast.Module) -> tuple[set[str], set[str]]:
    base_exception_names = {"BaseException"}
    builtins_module_names = {"builtins"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "builtins":
                    builtins_module_names.add(alias.asname or "builtins")
        elif isinstance(node, ast.ImportFrom) and node.module == "builtins":
            for alias in node.names:
                if alias.name == "BaseException":
                    base_exception_names.add(alias.asname or alias.name)
    return base_exception_names, builtins_module_names


def _catches_base_exception(
    expression: ast.expr | None,
    base_exception_names: set[str],
    builtins_module_names: set[str],
) -> bool:
    if isinstance(expression, ast.Name):
        return expression.id in base_exception_names
    if isinstance(expression, ast.Attribute):
        return (
            expression.attr == "BaseException"
            and isinstance(expression.value, ast.Name)
            and expression.value.id in builtins_module_names
        )
    if isinstance(expression, ast.Tuple):
        return any(
            _catches_base_exception(item, base_exception_names, builtins_module_names)
            for item in expression.elts
        )
    if isinstance(expression, ast.BinOp) and isinstance(expression.op, ast.BitOr):
        return _catches_base_exception(
            expression.left, base_exception_names, builtins_module_names
        ) or _catches_base_exception(
            expression.right, base_exception_names, builtins_module_names
        )
    return False


def _base_exception_handlers(tree: ast.Module) -> list[ast.ExceptHandler]:
    base_exception_names, builtins_module_names = _exception_aliases(tree)
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ExceptHandler)
        and _catches_base_exception(
            node.type, base_exception_names, builtins_module_names
        )
    ]


class _FinallyExitVisitor(ast.NodeVisitor):
    """Find exits in a finally suite without crossing nested function scopes."""

    def __init__(self) -> None:
        self.exits: list[ast.Return | ast.Break | ast.Continue] = []

    def visit_Return(self, node: ast.Return) -> None:
        self.exits.append(node)

    def visit_Break(self, node: ast.Break) -> None:
        self.exits.append(node)

    def visit_Continue(self, node: ast.Continue) -> None:
        self.exits.append(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return


def _finally_exit_statements(tree: ast.Module) -> list[ast.Return | ast.Break | ast.Continue]:
    exits = []
    try_nodes = (ast.Try, ast.TryStar)
    for node in ast.walk(tree):
        if isinstance(node, try_nodes):
            visitor = _FinallyExitVisitor()
            for statement in node.finalbody:
                visitor.visit(statement)
            exits.extend(visitor.exits)

    unique_exits = {}
    for node in exits:
        unique_exits[(type(node), node.lineno, node.col_offset)] = node
    return list(unique_exits.values())


@pytest.mark.base
def test_project_python_has_no_bare_except_pass_handlers():
    violations = []
    for path in _project_python_files():
        violations.extend(
            f"{path.relative_to(PROJECT_ROOT)}:{handler.lineno}"
            for handler in _bare_except_pass_handlers(_parse(path))
        )

    assert not violations, "Bare 'except: pass' handlers found: " + ", ".join(violations)


@pytest.mark.base
def test_project_python_does_not_catch_base_exception():
    violations = []
    for path in _project_python_files():
        violations.extend(
            f"{path.relative_to(PROJECT_ROOT)}:{handler.lineno}"
            for handler in _base_exception_handlers(_parse(path))
        )

    assert not violations, "BaseException handlers found: " + ", ".join(violations)


@pytest.mark.base
def test_project_python_has_no_control_flow_exit_in_finally():
    violations = []
    for path in _project_python_files():
        violations.extend(
            f"{path.relative_to(PROJECT_ROOT)}:{node.lineno} ({type(node).__name__})"
            for node in _finally_exit_statements(_parse(path))
        )

    assert not violations, "Control-flow exits in finally blocks found: " + ", ".join(violations)


@pytest.mark.base
def test_ast_guards_allow_specific_catches_and_nested_function_returns():
    tree = ast.parse(
        """
def operation():
    try:
        perform()
    except ValueError as error:
        recover(error)
    try:
        perform()
    finally:
        def cleanup_callback():
            return None
"""
    )

    assert _bare_except_pass_handlers(tree) == []
    assert _base_exception_handlers(tree) == []
    assert _finally_exit_statements(tree) == []


@pytest.mark.base
def test_ast_guards_detect_forbidden_handlers_and_finally_exits():
    tree = ast.parse(
        """
def operation():
    try:
        perform()
    except:
        pass
    try:
        perform()
    except (ValueError, BaseException):
        recover()
    for item in items:
        try:
            perform(item)
        finally:
            continue
"""
    )

    assert len(_bare_except_pass_handlers(tree)) == 1
    assert len(_base_exception_handlers(tree)) == 1
    exits = _finally_exit_statements(tree)
    assert len(exits) == 1
    assert isinstance(exits[0], ast.Continue)
