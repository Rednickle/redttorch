import re
import common_with_cwrap
from collections import OrderedDict

TYPE_TRANSLATIONS = {
    'THIndex_t': 'long',
    'THCTensor*': 'THTensor*',
}


def argument_to_declaration(arg):
    typ = TYPE_TRANSLATIONS.get(arg.type, arg.type)
    result = {
        'arg': typ + ' ' + arg.name,
    }
    if arg.is_optional:
        result['is_nullable'] = True
    return result


def function_to_declaration(func, backend):
    return {
        'mode': 'NN',
        'name': func.name,
        'types': ['Float', 'Double'],
        # skip state argument...
        'arguments': [argument_to_declaration(a) for a in func.arguments[1:]],
        'backends': [backend],
        'variants': ['function'],
    }


include_only = '(updateOutput|updateGradInput|accGradParameters|backward)$'
exclude = 'LookupTable'


#def run(paths):
#    functions = OrderedDict()
#    for path in paths:
#        #backend = 'CUDA' if re.search('THCU', path) else 'CPU'
#        for func in common_with_cwrap.parse_header(path):
#            if re.search(include_only, func.name) is None or re.search(exclude, func.name) is not None:
#                continue
#            if func.name in functions:
#                functions[func.name]['backends'].append(backend)
#            else:
#                functions[func.name] = function_to_declaration(func, backend)
#    declarations = [f for _, f in functions.items()]
#    return declarations

def parse(filename):
    with open(filename, 'r') as file:
        declarations = []
        in_declaration = False
        for line in file.readlines():
            if '[NativeFunction]' in line:
                in_declaration = True
                arguments = []
                declaration = {}
            elif '[/NativeFunction]' in line:
                in_declaration = False
                declaration['arguments'] = arguments
                declaration['mode'] = 'native'
                declarations.append(declaration)
            elif in_declaration:
                ls = line.strip().split(':')
                assert len(ls) == 2
                key = ls[0].strip()
                value = ls[1].strip()
                if key == 'arg':
                    arguments.append({key: value})
                else:
                    declaration[key] = value
        return declarations
