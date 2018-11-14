import pytest

@pytest.fixture
def testfile():
    return './test/testlogfile.log'


def test_compress(testfile):
    from logcompressor import logcompress
    import re

    comp = logcompress.RegExCompressor()

    comp.compress(testfile)
    
    assert len(comp._expressions) > 0

    # Take the output and write to a file in case we want to see it later.
    with open('./test/testcompressed.log', 'w+') as output:
        for cline in comp.cat_lines():
            output.write(cline + '\n')

    # Read the file we just wrote and check for the right stuff.
    with open('./test/testcompressed.log', 'r+') as output:
        outtext = output.read()
        assert len(outtext), "Nothing was output."
        assert '## EXPRESSIONS ##' in outtext, "No expressions in output"

        with open(testfile, 'r+') as inputtext:
            assert len(inputtext.read()) > len(outtext)

        token_expr = re.compile('(<.*?>)')
        
        tokens = [r.token for r in comp._expressions.values()]
        print(tokens)
        for match in token_expr.findall(outtext):
            assert match in tokens, match + " isn't in comp._expressions."

    assert comp.cat_all() is None, "Compressor object crashed in cat_all()"


def test_token():
    from logcompressor.logcompress import Token
    t = Token()
    assert t.token == '<0>', 'Token not initialized.'
    assert t.token == '<0>', 'Token not preserved.'
    assert next(t) == '<1>', 'Token did not increment to 1.'
    tokens = {'<0>', '<1>'}
    temp = next(t)
    for _ in range(100000):
        assert temp not in tokens, 'Duplicate token: ' + temp
        tokens.add(temp)
        temp = next(t)
