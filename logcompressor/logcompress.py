'''
Compress a log file by generating rules on the fly.

logcompress is a simple library designed to reduce log file size
without impacting log quality. It works by finding logfile
line-by-line text patterns and compressing them to a much shorter
string. It then provides a regex to undo the compression and search
tools for searching the compressed data.

Well, all those features are coming soon anyway!
'''
import re
import string
from collections import namedtuple, OrderedDict

FCS_MINIMUM = 5
CHUNK_SIZE = 25

RegExTuple = namedtuple(
    'RegExTuple',
    ['replaces', 'regex', 'token'])


class PhraseNode():
    '''Simple class for mapping relationships between words.
    Each instance is a node that links ordered words together,
    such as "foo" and "bar" in the phrase "foo bar".

    ex:
    foo bar the foo foo bar bar

    If we decide to map adjacent words in a "word1" -> "word2"
    style, node foo would have the following subnodes:
    -> bar
    -> foo

    bar would have:
    -> the
    -> bar

    methods:
    node['foo']
    -- dict-like indexing of subnodes.

    add_node(subnode)
      my_node.add_node(your_node)
    -- subnode is another node objects
    -- add a node as a subnode in the tree to current node.
    -- if the node is already present, add one to its counter
    -- subnodes can be accessed with nodename.nd_subnodename

    nodes
      my_node.nodes
    -- @property that returns a list of subnodes.

    navigate(depth, func, already_visited=None)
      my_nodes.navigate(3, print, already_visited=None)
    -- iterates through self.nodes and applies func to each node.
    -- continues iterating through the subnodes of the node for
       :depth: layers of subnodes.
    -- :already_visited: is an exclusion list to prevent infinite
       looping. You can also use it to exclude certain nodes by
       name. Use a set for O(1) speed.

    This class is implemented in the style of a singleton,
    but with a dict referencing named key:value pairs so that
    PhraseNode('bob') always returns the same node for bob.'''

    phrases = {}

    class __PhraseNode():

        def __init__(self, rootword):
            '''Creates a new phrase node from rootword. If rootword already has a node,
            use that.'''
            self._root = rootword
            self.parents = {}
            # dict of {parentword: count}.
            # example:
            #   self._root = 'def'
            #   self.parents['abc']
            #   >> 2
            # means that this string has shown up as 'abc def' two times.

            PhraseNode.phrases[rootword] = self

        def add_node(self, node):
            '''Adds a new node or increments the counter for an existing node.
            
            return: the number of nodes'''

            if 'nd_' + node._root not in self.__dict__:
                setattr(self, 'nd_' + node._root, node)
        
            if self._root in node.parents:
                node.parents[self._root] += 1
            else:
                node.parents[self._root] = 1

            return node.parents[self._root]

        def navigate(self, depth, func, already_visited=None):
            '''navigates the tree and applies func to all the nodes.

            ex: node.navigate(2, print)
                runs print(node) for this node and each of its subnodes to a
                depth of 2. This would effectively print all of the nodes
                on the tree to this depth.
            '''
            if not already_visited:
                already_visited = {self._root}
            else:
                already_visited.add(self._root)

            if depth:
                # get non-parsed nodes
                tree = [n for n in self.nodes
                        if n._root not in already_visited]

                for n in tree:
                    func(n)

                for n in tree:
                    n.navigate(depth-1, func=func,
                               already_visited=already_visited)

        @property
        def root(self):
            return self._root

        @property
        def nodes(self):
            return [getattr(self, node) for node in self.__dict__.keys()
                    if node.startswith('nd_')]

        def __getitem__(self, nodename):
            return self.__dict__['nd_' + nodename]

        def __str__(self):
            return self._root

        def __repr__(self):
            return '<PhaseTree Node: {root}, subnodes: {nodes}>'.format(
                root=self._root,
                nodes=' | '.join((str(n) for n in self.nodes))
            )

    def __init__(self, rootword):
        if rootword not in PhraseNode.phrases:
            PhraseNode.phrases[rootword] = PhraseNode.__PhraseNode(rootword)
        self.__key = rootword

    def __getattr__(self, attr):
        return getattr(PhraseNode.phrases[self.__key], attr)

    def __getitem__(self, item):
        return PhraseNode.phrases[self.__key][item]

    def __repr__(self):
        return repr(PhraseNode.phrases[self.__key])

    def __str__(self):
        return str(PhraseNode.phrases[self.__key])
        

class RegExCompressor():
    '''Does the compressing work by finding common two-word pairs,
    compressing them into a unique value, and repeating.'''

    def __init__(self):
        self.root = PhraseNode('\n')
        self._expressions = OrderedDict()  # list of RegExTuples
        self.token = Token()
        self.compressed_output = None
    
    def compress(self, filename):
        with open(filename) as f:
            line = f.readline()
            chunk = []
            self.compressed_output = []
            line_counter = 0
            while line:
                line_counter += 1
                chunk.append(line)
                if line_counter >= CHUNK_SIZE:
                    chunk = self.press(chunk)
                    for compressed_line in chunk:
                        self.compressed_output.append(compressed_line)
                    chunk = []
                    line_counter = 0
                line = f.readline()

        return self.compressed_output

    def press(self, chunk):
        '''Takes a list of strings and compresses them by detecting
        short patterns. Adds the patterns to an internal list for
        later use.

        in:
          - chunk: uncompressed lines in a list

        out: [line1, line2, line3] etc after compressing'''

        chunk = self.encode(chunk)
        changes = True
        while changes:
            changes = self.press_mainloop(chunk)

        return chunk

    def cat_lines(self):
        '''Generator for concatenating the lines in self.compressed_output
        after applying the regexes.'''

        for line in self.compressed_output:
            line, trailer = self.split_trailer(line)
            line, _ = self.apply_regexes(line)
            yield line.rstrip() + trailer

        yield "\n## EXPRESSIONS ##\n"
        yield ', '.join(reg for reg in self._expressions)
        
    def cat_all(self):
        '''Prints the compressed output to stdout.'''
        for line in self.cat_lines():
            print(line)

    def press_mainloop(self, chunk):
        '''Generates new expressions that can be used to compress
        the file in a loop, then applies them to the chunk.'''
        changes = 0
        todo_list = []

        for index, line in enumerate(chunk):
            line, trailer = self.split_trailer(line)
            chunk[index], changes_delta = self.apply_regexes(line)
            changes += changes_delta
            self.map_nodes(line, index, todo_list)

            line = line + trailer

        # First pass is done. Catch up on our todo list.
        for index, line in enumerate(chunk):
            for todo_index, regex in enumerate(todo_list):
                regex, stopline = regex[0], regex[1]
                chunk[index], changes_delta = \
                    self.apply_one(line, regex)
                changes += changes_delta

                # if todo_list element is caught up, remove the current
                # element in o(1) time by overwriting it.
                if todo_index == stopline and todo_index != len(todo_list) - 1:
                    todo_list[todo_index] = todo_list.pop()

        return changes

    def gen_regex(self, node1, node2):
        '''Gets a new token and makes a regex from that token.'''
        replaces = node1.root + " " + node2.root
        if replaces not in self._expressions:
            regex = replaces
            token = next(self.token)
            self._expressions[replaces] = RegExTuple(
                replaces=replaces,
                regex=regex,
                token=token)
            return self._expressions[replaces]

    def apply_regexes(self, line):
        '''
        Applies expressions from self.expressions to the chunk.
        Returns the line and the number of inline substitutions.
        '''
        changes = 0
        for _, regex in self._expressions.items():
            line, cdelta = self.apply_one(line, regex)
            changes += cdelta

        return (line, changes)

    def apply_one(self, line, regex):
        '''Applies one regex to the line.'''
        line, changes = re.subn(regex.regex, regex.token, line)
        return (line, changes)

    def map_nodes(self, line, index, todo_list):
        '''
        Add new nodes to the tree from a line of text.
        Applies existing compression expressions.
        Makes new compression regex expressions for popular nodes.

        There is generally no need to call this from outside of the
        class.
        '''

        lastnode = self.root
        for word in line.split():
            if word:
                node = PhraseNode(word)
                count = lastnode.add_node(node)

                if count >= 5 and lastnode != self.root:
                    new_reg = self.gen_regex(lastnode, node)
                    if new_reg:
                        todo_list.append((new_reg, index))

                lastnode = node

    def encode(self, chunk):
        '''Encodes the entire chunk according to the encoding function.'''
        cleaned = [encode_punct_and_digits(line) for line in chunk]
        return cleaned

    def split_trailer(self, line):
        trailer = re.search(' {(.*)}$', line.rstrip())
        trailer = trailer.group(1) if trailer else ''

        items = re.findall('_\$_(.*?)_\$_', line)
        newtraileritems = ' '.join((m for m in items)) if items else ''

        if trailer or newtraileritems:
            trailer = ' {' + (trailer + ' ' + newtraileritems).strip() + '}'
        # trailer is now empty string or formatted like' {: ; 123}'

        # clean the line
        line = clean_encoding(line)
        return (line.rstrip(), trailer)


class Token:
    '''
    Returns an iterator that generates unique consecutive tokens.
    Tokens are generated using Token.chars as the character
    set and cycling through them, adding digits as tokens are exhausted.
    '''
    chars = ''.join((string.digits, string.ascii_letters))

    def __init__(self):
        self.generators = [self.get_gen()]
        self.digits = [next(self.generators[0])]

    def get_gen(self):
        return (char for char in Token.chars)

    @property
    def token(self):
        '''Returns the most recent token but does not increment the
        counter'''
        return ''.join(('<', ''.join(self.digits), '>'))

    def __next__(self):
        '''Increments the token generator and returns a new unique token.'''
        index = 0
        while index > 0 - len(self.digits):
            try:
                self.digits[index] = next(self.generators[index])
                break
            except StopIteration:
                self.generators[index] = self.get_gen()
                self.digits[index] = next(self.generators[index])
                index -= 1
                if index == -1 * len(self.digits):
                    gen = self.get_gen()
                    self.generators.append(gen)
                    self.digits.append(next(gen))
                    break

        return self.token

    def __iter__(self):
        return self


def encode_punct_and_digits(line):
    '''Encodes punctuation and digits.'''
    line = re.sub(
        "([\d|!\"#$%&'()*+,./:;<=>?@[\\]^`{|}~]+)", r'_$_\1_$_',
        line)
    return line


def clean_encoding(line):
    '''returns an encoding-stripped line.'''
    if line:
        line = re.sub("_\$_.*?_\$_", '#', line)
        line = re.sub(" \{.*\}$", '', line)
        return line if line else ''
    else:
        return ''


def press_duplicate_lines(self, chunk):
    '''Not implemented yet.'''
    #TODO
    lines = {}
    for linenum, line in enumerate(chunk):
        header, trailer = self.split_trailer(line)
        if header not in lines:
            print(header)
            lines[line] = []

        lines[header].append((linenum, trailer))

    print(lines['<n1>'])


if __name__ == '__main__':
    comp = RegExCompressor()
    comp.compress('testlogfile.log')
    comp.cat_all()