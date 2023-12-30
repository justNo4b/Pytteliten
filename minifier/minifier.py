import re
from dataclasses import dataclass
import subprocess

#################
# Name mangling #
#################

# KEY: TOKEN
# VALUE: MANGLED NAME
names = dict()
TYPES = ['int', 'void', 'uint16_t', 'uint32_t', 'uint64_t',
         'bool', 'auto', 'int32_t', 'string', 'vector', 'istringstream']
KEYWORDS = TYPES + ['return', 'printf', 'struct', 'main', 'std', 'push_back', 'back',
                    'pop_back', 'reserve', 'cout', '__builtin_bswap64', '__builtin_ctzll', 'const', 'assert',
                    'endl', 'for', 'while', 'swap', 'if', 'else', 'char', 'abs', 'getline',
                    'break', 'length', 'switch', 'case', 'cin', 'empty', 'continue', 'size',
                    'default', 'using', 'namespace', '__builtin_popcountll', 'stoi', 'chrono', 'second',
                    'high_resolution_clock', 'duration_cast', 'milliseconds', 'now', 'max', 'pair', 'stable_sort', 'greater', 'min', 'memset', 'sizeof']
global counter, resets
counter = 65  # ASCII A
resets = 0  # Number of times the counter has exceeded reset back to A


def generate_name(token: str) -> str:
    """Generates a new name for a token. If the token has already been before, return that name to keep coherency."""
    global counter, resets

    # Already mangled
    if token in names:
        return names[token]

    # Generate a new name
    names[token] = chr(counter) * (resets + 1)

    # Jump to lowercase letters
    if counter == 90:  # previous char was ASCII Z
        counter = 96   # ASCII before 'a', because we increment after this to get to 'a'

    # Increment counter so that the next name is different
    counter += 1
    if counter > 122:  # ASCII z
        counter = 65
        resets += 1

    return names[token]


def fetch_tokens(content: str) -> list:
    """Fetches all the tokens from the source code. A token is a word, number, whitespace, symbol, etc."""
    return [t for t in re.split('([^\w])', content) if t]


def is_name(token: str) -> bool:
    """A name of /something/. Either a variable, function, class, etc."""
    return token and (token[0].isalpha() or token.startswith('_'))


def is_keyword(token: str) -> bool:
    """Returns whether the token is a CPP keyword used in the engine."""
    return token in KEYWORDS


def renamable(token: str) -> bool:
    """Returns whether the token is renamable, i.e names that aren't types/keywords."""
    return not is_keyword(token) and is_name(token)


def attach_eligible(token: str) -> bool:
    """Returns whether a token is eligible to be attached together to save whitespace."""
    # Some c++ numbers have suffixes like 1ULL which is 1 as an unsigned long long.
    # We only check the first char of the token to be numeric to catch these cases.
    return token and not (is_name(token) or token[0].isnumeric())


def attachable_tokens(first: str, second: str) -> bool:
    """Returns whether two tokens can be attached together to save whitespace."""
    return attach_eligible(first) or attach_eligible(second)


def group_tokens(token_list: list, start: list, end: list, include_end: bool = True, include_space: bool = True) -> list:
    """Finds ``start`` tokens and concatenates everything from ``start``-``end``."""
    output = []

    # This is the start index where we look for first index such that [idx + len(start)] <=> start
    start_idx = 0

    while start_idx < len(token_list):

        # end must be after the start, so set it to start + 1
        end_idx = start_idx + 1

        # Verify that there is still space in the token list in the first condition.
        # In the second condition, check that start that was passed in ==
        # token_list starting at start_idx till start_idx + len(start).
        # Recollect that start_idx is just an idx, and start_idx + len(start) is a
        # subsequence of token_list of size len(start)
        if (start_idx + len(start) <= len(token_list)) and (start == token_list[start_idx:start_idx + len(start)]):

            # Search all possible end idxs from the end of the start to the end of the string.
            # Give padding for the size of the end token.
            for possible_end_idx in range(end_idx + len(start) - 1, len(token_list) - len(end) + 1):

                # Similar to the first condition, check if from end idx to len(end) == passed in end.
                if end == token_list[possible_end_idx: possible_end_idx + len(end)]:
                    # Just include the whole end if that param is true.
                    end_idx = possible_end_idx + \
                        len(end) if include_end else possible_end_idx
                    break

        # Self-explanatory, join everything from start to end. If we never found anything this is
        # start:start+1 because we set end_idx to start + 1 at the beginning.
        # This adds just the token if we found nothing.
        grouped_tokens = "".join(token_list[start_idx:end_idx])
        if not include_space and end_idx != start_idx + 1:
            grouped_tokens = grouped_tokens.replace(" ", "")

        output.append(grouped_tokens)

        # We searched everything from start to end, so no need to research. set start to old end.
        start_idx = end_idx

    return output


def group(tokens: list) -> list:
    """Groups all relevant tokens together, such as comments, strings and deletion regions."""
    # Create token groups such as comments, strings, etc.
    tokens = group_tokens(tokens, ['"'], ['"'])              # Strings
    tokens = group_tokens(tokens, ['/', '*'], ['*', '/'])    # Block comments
    tokens = group_tokens(tokens, ['[', '['], [']', ']'])    # Attributes
    tokens = group_tokens(tokens, ['#', 'include'], ['\n'], include_space=False)  # Includes

    # Deletion regions
    tokens = group_tokens(tokens, ['#', 'ifndef', ' ', 'MINIFIED'], ['#', 'endif'])

    tokens = group_tokens(tokens, ['/', '/'], ['\n'], include_end=False)  # Line comments
    tokens = group_tokens(tokens, ["'"], ["'"])               # Chars

    return tokens


def strip(tokens: list) -> list:
    """Strips out all tokens that shouldn't be present in final code."""
    new_tokens = []
    for token in tokens:
        # line/block comments, deletion regions and attributes
        if token.startswith('//') or token.startswith('/*') or token.startswith('[[') or token.startswith('#ifndef'):
            continue

        # newlines, spaces, consts...
        if token == '\n' or token.isspace() or token == 'const':
            continue

        new_tokens.append(token)

    return new_tokens


@dataclass
class Struct:
    name: str
    fields: list
    functions: list
    top_lvl_used: list

    def __init__(self, name: str):
        self.fields = dict()
        self.functions = dict()
        self.top_lvl_used = []
        self.name = name


@dataclass
class Function:
    args: dict()
    variables: dict()

    def __init__(self):
        self.args = dict()
        self.variables = dict()


def is_type(info: dict, token: str) -> bool:
    """Check if the token is a type."""
    return token in TYPES or token in info


def preceded_by_type(info: dict, prev: str, prev_prev: str) -> bool:
    """Check if token is preceeded by type."""
    return is_type(info, prev) or (prev in ['>', '&'] and is_type(info, prev_prev))


def scope_change(token: str, opener: str, closer: str) -> int:
    """Calculates change in scope."""
    return (token == opener) - (token == closer)


def get_stats(tokens: list) -> dict:
    """Analyses struct and function structure, recording frequency stats as it goes."""
    entering_function = False
    struct = None
    function = None
    struct_scope = 0
    function_scope = 0
    parenth_depth = 0
    structinfo = {None: Struct("Top Level")}
    prev = None
    prev_prev = None

    for i, token in enumerate(tokens):
        # Handle exiting function
        if not entering_function and function is not None:
            function_scope += scope_change(token, '{', '}')
            if function_scope == 0:
                function = None

        # Record args
        if entering_function:
            if token == '(':
                parenth_depth += 1
            elif token == ')':
                parenth_depth -= 1
            elif parenth_depth > 0 and tokens[i + 1] in [',', ')'] and token not in TYPES:
                structinfo[struct].functions[function].args[token] = 1
            if parenth_depth == 0:
                entering_function = False

        # Found a function
        following = tokens[i + 1] if i + 1 < len(tokens) else None
        if is_name(token) and preceded_by_type(structinfo, prev, prev_prev) and following == '(':
            entering_function = True
            function = token
            structinfo[struct].functions[token] = Function()

        if function is not None:
            # Found function arg
            if token in structinfo[struct].functions[function].args:
                structinfo[struct].functions[function].args[token] += 1

            # Found local variable
            if token in structinfo[struct].functions[function].variables:
                structinfo[struct].functions[function].variables[token] += 1

            # Found declaration of local variable
            if not entering_function and is_name(token) and preceded_by_type(structinfo, prev, prev_prev):
                structinfo[struct].functions[function].variables[token] = 1

        # Exiting struct?
        if struct is not None:
            struct_scope += scope_change(token, '{', '}')
            if struct_scope == 0:
                struct = None

        # Now in a struct
        if prev == "struct":
            struct = token
            structinfo[struct] = Struct(token)

        # Found a struct field
        if struct_scope == 1 and is_name(token) and function is None and preceded_by_type(structinfo, prev, prev_prev):
            structinfo[struct].fields[token] = 1

        if token in structinfo[struct].fields:
            structinfo[struct].fields[token] += 1

        # Record what top level functions are used in each struct
        if token in structinfo[None].functions and token not in structinfo[struct].top_lvl_used and struct is not None:
            structinfo[struct].top_lvl_used.append(token)

        prev_prev = prev
        prev = token

    return structinfo


def print_stats(structinfo: dict):
    """Pretty print stats."""
    import pprint
    pp = pprint.PrettyPrinter(indent=4)
    for struct in structinfo:
        pp.pprint(structinfo[struct])
        print("")


def sort_dict(dictionary: dict) -> dict:
    """Sorts dictionary in descending order by value."""
    return {k: v for k, v in sorted(dictionary.items(), key=lambda item: -item[1])}


def get_ir_renames(structinfo: dict):
    """Works out how to rename tokens to intermediate-representation based on given statistics."""
    ir = dict()
    fields = dict()
    methods = dict()
    top_lvl_used = set()

    # Go through each struct in turn
    for i, struct in enumerate(structinfo):
        ir[struct] = Struct("struct" + str(i))

        # Choose struct field names
        j = 0
        sorted_fields = sort_dict(structinfo[struct].fields)
        for field in sorted_fields:
            if field in fields:
                ir[struct].fields[field] = fields[field]
                continue
            fieldname = "field" + str(j)
            ir[struct].fields[field] = fieldname
            fields[field] = fieldname
            j += 1

        # Choose function names
        for x, func in enumerate(structinfo[struct].functions):
            if struct is not None:
                methods[func] = "func" + str(x)

            ir[struct].functions[func] = Function()

            # Choose function argument names
            sorted_args = sort_dict(structinfo[struct].functions[func].args)
            for y, arg in enumerate(sorted_args):
                ir[struct].functions[func].args[arg] = "arg" + str(y)

            # Choose local variable names
            sorted_vars = sort_dict(
                structinfo[struct].functions[func].variables)
            for y, var in enumerate(sorted_vars):
                ir[struct].functions[func].variables[var] = "var" + str(y)

        for func in structinfo[struct].top_lvl_used:
            top_lvl_used.add(func)

    i, j = 0, 0
    for func in structinfo[None].functions:
        if func in top_lvl_used:
            methods[func] = "topfunc" + str(i)
            i += 1
        else:
            if func in methods:
                continue
            methods[func] = "main" if func == "main" else "func" + str(j)
            j += 1

    return ir, fields, methods


def to_ir(tokens: list, ir: dict, fields: dict, methods: dict) -> list:
    """Transforms tokens into intermediate representation with given renames."""
    new_tokens = []
    entering_function = False
    struct = None
    function = None
    struct_scope = 0
    function_scope = 0
    parenth_depth = 0
    prev = None

    for token in tokens:
        # Handle exiting function
        if not entering_function and function != None:
            function_scope += scope_change(token, '{', '}')
            if function_scope == 0:
                function = None

        # Record args
        if entering_function:
            parenth_depth += scope_change(token, '(', ')')
            if parenth_depth == 0:
                entering_function = False

        if token in methods and function is None:
            function = token
            entering_function = True

        # Exiting struct?
        if struct != None:
            struct_scope += scope_change(token, '{', '}')
            if struct_scope == 0:
                struct = None

        # We've got the struct name
        if prev == "struct":
            struct = token

        # Rename if appropriate
        if function is not None and token in ir[struct].functions[function].args:
            token = ir[struct].functions[function].args[token]
        elif token in fields:
            token = fields[token]
        elif token in methods:
            token = methods[token]
        elif function is not None and token in ir[struct].functions[function].variables:
            token = ir[struct].functions[function].variables[token]

        prev = token
        new_tokens.append(token)

    return new_tokens


def get_frequencies(tokens: list) -> dict:
    """Works out frequency of each token."""
    freq = dict()

    for token in tokens:
        if not renamable(token):
            continue

        freq[token] = (freq[token] + 1) if token in freq else 1

    return sort_dict(freq)


def minify(content: str, verbose: bool):
    """Combines all steps, producing a fully-minified file."""
    tokens = fetch_tokens(content)
    tokens = group(tokens)
    tokens = strip(tokens)

    structinfo = get_stats(tokens)
    if verbose:
        print_stats(structinfo)

    ir, fields, methods = get_ir_renames(structinfo)
    tokens = to_ir(tokens, ir, fields, methods)

    # Write IR to file, for easier debugging
    prev = None
    ir_tokens = []
    for token in tokens:
        if prev and not attachable_tokens(prev, token):
            ir_tokens.append(' ')
        prev = token
        ir_tokens.append(token)
    with open('plir.cpp', 'w') as f:
        f.write(''.join(ir_tokens))

    # Make it look nice
    try:
        subprocess.run(["clang-format", "--style=file", "-i",
                       "plir.cpp"], stdout=subprocess.DEVNULL)
    except:
        try:
            subprocess.run(["./clang-format", "--style=file",
                           "-i", "plir.cpp"], stdout=subprocess.DEVNULL)
        except:
            pass

    # Now the real minifying begins
    new_tokens = []
    prev = None

    # Replace true and false with 1 and 0
    names['true'] = '1'
    names['false'] = '0'

    # Don't rename keywords
    for kw in KEYWORDS:
        names[kw] = kw

    # Generate names in order of frequency
    freq = get_frequencies(tokens)
    for token in freq:
        names[token] = generate_name(token)

    for token in tokens:
        # Add a seperator between tokens that can't be attached to each other.
        # For example: Two names (int main)
        if prev and not attachable_tokens(prev, token):
            new_tokens.append(' ')

        # If the token is a name, but not a keyword, we mangle it.
        if renamable(token):
            token = names[token]

        prev = token
        new_tokens.append(token)

    with open('pytteliten-mini.cpp', 'w') as f:
        f.write(''.join(new_tokens))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description="Pytteliten minifier")
    parser.add_argument('-v', '--verbose', action="store_true", help="Print detailed statistics during minification.")

    assert fetch_tokens('int main() { return 0; }') == [
        'int', ' ', 'main', '(', ')', ' ', '{', ' ', 'return', ' ', '0', ';', ' ', '}']
    assert fetch_tokens('hehe = 1;') == ['hehe', ' ', '=', ' ', '1', ';']
    assert fetch_tokens('a_very_long_variable_name') == [
        'a_very_long_variable_name']
    assert fetch_tokens("test\t\ntest") == ["test", "\t", "\n", "test"]

    assert is_name('a')
    assert is_name('a_')
    assert is_name('a_1')
    assert is_name('__AA')
    assert is_name('variable')
    assert is_name('my_favorite_number_100000')
    assert is_name('int')
    assert not is_name('123')
    assert not is_name('1a2b3c')
    assert not is_name('')
    assert not is_name(' ')
    assert not is_name('\n')

    assert renamable('abcdefg')
    assert renamable('a')
    assert renamable('a_123')
    assert not renamable('main')
    assert not renamable('int')
    assert not renamable('return')
    assert not renamable('1000')

    assert attach_eligible(')')
    assert attach_eligible('+')
    assert attach_eligible('{')
    assert not attach_eligible('a_name')
    assert not attach_eligible('1')
    assert not attach_eligible('main')

    assert attachable_tokens('1', '+')
    assert attachable_tokens('{', '}')
    assert attachable_tokens('(', ')')
    assert attachable_tokens('{', 'printf')
    assert attachable_tokens('coolboy99', '+')
    assert not attachable_tokens('int', 'main')
    assert not attachable_tokens('1', '2')
    assert not attachable_tokens('return', '0')

    assert group_tokens(["a", "b", "c", "d"], ["a"], ["b"]) == ["ab", "c", "d"]
    assert group_tokens(["a", "b", "c", "d"], ["b"], ["c"]) == ["a", "bc", "d"]
    assert group_tokens(["a", "b", "c", "d"], ["c"], ["d"]) == ["a", "b", "cd"]
    assert group_tokens(["a", "b", "c", "d"], ["a"], ["d"]) == ["abcd"]
    assert group_tokens(["a", "b", "c", "d"], ["c"], [
        "b"]) == ["a", "b", "c", "d"]
    assert group_tokens(["a", "b", "c", "d"], ["b"], [
        "e"]) == ["a", "b", "c", "d"]
    assert group_tokens(["a", "b", "c", "d"], ["b"], [
        "b"]) == ["a", "b", "c", "d"]
    assert group_tokens(["a", "b", "c", "d"], [
                        "a", "b"], ["c"]) == ["abc", "d"]
    assert group_tokens(["a", "b", "c", "d"], ["a"],
                        ["b", "c"]) == ["abc", "d"]
    assert group_tokens(["a", "b", "c", "d"], [
                        "a", "b", "c"], ["d"]) == ["abcd"]
    assert group_tokens(["a", "b", "c", "d"], ["a"],
                        ["c"], True) == ["abc", "d"]
    assert group_tokens(["a", "b", "c", "d"], ["a"], [
        "c"], False) == ["ab", "c", "d"]
    assert group_tokens(["a", "b", "c", "d"], ["c"], [
        "e"]) == ["a", "b", "c", "d"]
    assert group_tokens(["a", "b", "c", "d"], ["e"], [
        "c"]) == ["a", "b", "c", "d"]

    with open('main.cpp', 'r') as f:
        src = f.read()

        minify(src, parser.parse_args().verbose)
