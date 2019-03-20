import argparse
import os

import yaml
from collections import OrderedDict

import sys
from os import path
sys.path.append(path.dirname(path.abspath(__file__)))

import cwrap_parser
import nn_parse
import native_parse
import preprocess_declarations
import function_wrapper

from code_template import CodeTemplate


# This file is the top-level entry point for code generation in ATen.
# It takes an arbitrary number of arguments specifying metadata files to
# process (.cwrap, .yaml and .h) and outputs a number generated header
# and cpp files in ATen/ (see invocations of 'write' for each file that
# is written.) It is invoked from cmake; look for the 'cwrap_files'
# variable for an up-to-date list of files which are passed.

parser = argparse.ArgumentParser(description='Generate ATen source files')
parser.add_argument('files', help='cwrap files', nargs='+')

parser.add_argument(
    '-s',
    '--source-path',
    help='path to source directory for ATen',
    default='.')
parser.add_argument(
    '-o',
    '--output-dependencies',
    help='output a list of dependencies into the given file and exit')
parser.add_argument(
    '-d', '--install_dir', help='output directory', default='ATen')
parser.add_argument(
    '--rocm',
    action='store_true',
    help='reinterpret CUDA as ROCm/HIP and adjust filepaths accordingly')
options = parser.parse_args()
gen_to_source = os.environ.get('GEN_TO_SOURCE')  # update source directly as part of gen
if not gen_to_source:
    core_install_dir = os.path.join(options.install_dir, 'core_tmp') if options.install_dir is not None else None
else:
    core_install_dir = os.path.join(options.source_path, 'core')

if options.install_dir is not None and not os.path.exists(options.install_dir):
    os.makedirs(options.install_dir)
if core_install_dir is not None and not os.path.exists(core_install_dir):
    os.makedirs(core_install_dir)


class FileManager(object):
    def __init__(self, install_dir=None):
        self.install_dir = install_dir if install_dir else options.install_dir
        self.filenames = set()
        self.outputs_written = False
        self.undeclared_files = []

    def will_write(self, filename):
        filename = '{}/{}'.format(self.install_dir, filename)
        if self.outputs_written:
            raise Exception("'will_write' can only be called before " +
                            "the call to write_outputs, refactor so outputs are registered " +
                            "before running the generators")
        self.filenames.add(filename)

    def _write_if_changed(self, filename, contents):
        try:
            with open(filename, 'r') as f:
                old_contents = f.read()
        except IOError:
            old_contents = None
        if contents != old_contents:
            with open(filename, 'w') as f:
                f.write(contents)

    def write_outputs(self, filename):
        """Write a file containing the list of all outputs which are
        generated by this script."""
        self._write_if_changed(
            filename,
            ''.join(name + ";" for name in sorted(self.filenames)))
        self.outputs_written = True

    def write(self, filename, s, env=None):
        filename = '{}/{}'.format(self.install_dir, filename)
        if isinstance(s, CodeTemplate):
            assert env is not None
            env['generated_comment'] = "@" + "generated by aten/src/ATen/gen.py"
            s = s.substitute(env)
        self._write_if_changed(filename, s)
        if filename not in self.filenames:
            self.undeclared_files.append(filename)
        else:
            self.filenames.remove(filename)

    def check_all_files_written(self):
        if len(self.undeclared_files) > 0:
            raise Exception(
                "trying to write files {} which are not ".format(self.undeclared_files) +
                "in the list of outputs this script produces. " +
                "use will_write to add them.")
        if len(self.filenames) > 0:
            raise Exception("Outputs declared with 'will_write' were " +
                            "never written: {}".format(self.filenames))


TEMPLATE_PATH = options.source_path + "/templates"
GENERATOR_DERIVED = CodeTemplate.from_file(
    TEMPLATE_PATH + "/GeneratorDerived.h")
TYPE_DERIVED_CPP = CodeTemplate.from_file(TEMPLATE_PATH + "/TypeDerived.cpp")
SPARSE_TYPE_DERIVED_CPP = CodeTemplate.from_file(TEMPLATE_PATH + "/SparseTypeDerived.cpp")
TYPE_DERIVED_H = CodeTemplate.from_file(TEMPLATE_PATH + "/TypeDerived.h")
TYPE_H = CodeTemplate.from_file(TEMPLATE_PATH + "/Type.h")
TYPE_EXTENDED_INTERFACE_H = CodeTemplate.from_file(TEMPLATE_PATH + "/TypeExtendedInterface.h")
TYPE_DEFAULT_H = CodeTemplate.from_file(TEMPLATE_PATH + "/TypeDefault.h")
TYPE_DEFAULT_CPP = CodeTemplate.from_file(TEMPLATE_PATH + "/TypeDefault.cpp")
TYPE_EXTENSION_H = CodeTemplate.from_file(TEMPLATE_PATH + "/TypeExtension.h")
TYPE_EXTENSION_CPP = CodeTemplate.from_file(TEMPLATE_PATH + "/TypeExtension.cpp")
TYPE_EXTENSION_DERIVED_H = CodeTemplate.from_file(TEMPLATE_PATH + "/TypeExtensionDerived.h")
TYPE_EXTENSION_DERIVED_CPP = CodeTemplate.from_file(TEMPLATE_PATH + "/TypeExtensionDerived.cpp")

LEGACY_TH_DISPATCHER_H = CodeTemplate.from_file(TEMPLATE_PATH + "/LegacyTHDispatcher.h")
LEGACY_TH_DISPATCHER_CPP = CodeTemplate.from_file(TEMPLATE_PATH + "/LegacyTHDispatcher.cpp")
LEGACY_TH_DISPATCHER_DERIVED_CPP = CodeTemplate.from_file(TEMPLATE_PATH + "/LegacyTHDispatcherDerived.cpp")
LEGACY_TH_DISPATCHER_DERIVED_H = CodeTemplate.from_file(TEMPLATE_PATH + "/LegacyTHDispatcherDerived.h")

REGISTER_CPU_H = CodeTemplate.from_file(TEMPLATE_PATH + "/RegisterCPU.h")
REGISTER_CPU_CPP = CodeTemplate.from_file(TEMPLATE_PATH + "/RegisterCPU.cpp")

REGISTER_CUDA_H = CodeTemplate.from_file(TEMPLATE_PATH + "/RegisterCUDA.h")
REGISTER_CUDA_CPP = CodeTemplate.from_file(TEMPLATE_PATH + "/RegisterCUDA.cpp")

TENSOR_H = CodeTemplate.from_file(TEMPLATE_PATH + "/Tensor.h")
TENSOR_METHODS_H = CodeTemplate.from_file(TEMPLATE_PATH + "/TensorMethods.h")

FUNCTIONS_H = CodeTemplate.from_file(TEMPLATE_PATH + "/Functions.h")
LEGACY_TH_FUNCTIONS_H = CodeTemplate.from_file(TEMPLATE_PATH + "/LegacyTHFunctions.h")

NATIVE_FUNCTIONS_H = CodeTemplate.from_file(TEMPLATE_PATH + "/NativeFunctions.h")

EXTENSION_BACKEND_REGISTRATION_H = CodeTemplate.from_file(TEMPLATE_PATH + "/ExtensionBackendRegistration.h")

TYPE_REGISTER = CodeTemplate("""\
context->registerType(Backend::${backend}, ScalarType::${scalar_type}, new ${type_name}());
""")

EXTENSION_BACKEND_REGISTER_SWITCH = CodeTemplate("""\
case Backend::${Backend}:
    ${Type}Dispatch::register_function(schema, fn);
    break;
""")

core_file_manager = FileManager(core_install_dir)
file_manager = FileManager()
cuda_file_manager = FileManager()

generators = {
    'CPUGenerator.h': {
        'name': 'CPU',
        'th_generator': 'THGenerator * generator;',
        'header': 'TH/TH.h',
    },
    'CUDAGenerator.h': {
        'name': 'CUDA',
        'th_generator': '',
        'header': 'THC/THC.h' if not options.rocm else 'THH/THH.h'
    },
}

backends = ['CPU', 'CUDA']
densities = ['Dense', 'Sparse', 'Mkldnn']  # TODO: layout instead of densities?
extension_backends = ['MSNPU', 'XLA']

# scalar_name, c_type, accreal, th_scalar_type, is_floating_type
scalar_types = [
    ('Bool', 'uint8_t', 'BoolAccrealNotDefined', 'uint8_t', False),
    ('Byte', 'uint8_t', 'Long', 'uint8_t', False),
    ('Char', 'int8_t', 'Long', 'int8_t', False),
    ('Double', 'double', 'Double', 'double', True),
    ('Float', 'float', 'Double', 'float', True),
    ('Int', 'int', 'Long', 'int32_t', False),
    ('Long', 'int64_t', 'Long', 'int64_t', False),
    ('Short', 'int16_t', 'Long', 'int16_t', False),
    ('Half', 'Half', 'Double', 'at::Half', True),
]

# shared environment for non-derived base classes Type.h Tensor.h Storage.h
top_env = {
    'cpu_type_registrations': [],
    'cpu_type_headers': [],
    'cuda_type_registrations': [],
    'cuda_type_headers': [],
    'pure_virtual_type_method_declarations': [],
    'pure_virtual_extended_type_method_declarations': [],
    'type_method_declarations': [],
    'type_method_definitions': [],
    'tensor_method_declarations': [],
    'tensor_method_definitions': [],
    'function_declarations': [],
    'function_definitions': [],
    'type_ids': [],
    'native_function_declarations': [],
    'extension_backend_headers': [],
    'extension_backend_register_switches': [],
}


def dict_representer(dumper, data):
    return dumper.represent_dict(data.items())


def postprocess_output_declarations(output_declarations):
    # ensure each return has a name associated with it
    for decl in output_declarations:
        has_named_ret = False
        for n, ret in enumerate(decl.returns):
            if 'name' not in ret:
                assert not has_named_ret
                if decl.inplace:
                    ret['name'] = 'self'
                elif len(decl.returns) == 1:
                    ret['name'] = 'out'
                else:
                    ret['name'] = 'out' + str(n)
            else:
                has_named_ret = True

    def remove_key_if_none(dictionary, key):
        if key in dictionary.keys() and dictionary[key] is None:
            del dictionary[key]
        return dictionary

    return [remove_key_if_none(decl._asdict(), 'buffers')
            for decl in output_declarations]


def format_yaml(data):
    if options.output_dependencies:
        # yaml formatting is slow so don't do it if we will ditch it.
        return ""
    noalias_dumper = yaml.dumper.SafeDumper
    noalias_dumper.ignore_aliases = lambda self, data: True
    # Support serializing OrderedDict
    noalias_dumper.add_representer(OrderedDict, dict_representer)
    # Some yaml parsers (e.g. Haskell's) don't understand line breaks.
    # width=float('Inf') turns off optional line breaks and improves
    # the portability of the outputted yaml.
    return yaml.dump(data, default_flow_style=False, Dumper=noalias_dumper, width=float('Inf'))


def generate_storage_type_and_tensor(backend, density, scalar_type, declarations):
    scalar_name, c_type, accreal, th_scalar_type, is_floating_type = scalar_type
    env = {}
    density_tag = density if density != 'Dense' else ''
    env['Density'] = density
    env['ScalarName'] = scalar_name
    env['ScalarType'] = c_type
    env['THScalarType'] = th_scalar_type
    env['AccScalarName'] = accreal
    env['isFloatingType'] = is_floating_type
    env['isIntegralType'] = not is_floating_type
    env['Type'] = "{}{}{}Type".format(density_tag, backend, scalar_name)
    env['DenseTensor'] = "{}{}Tensor".format(backend, scalar_name)
    env['Backend'] = density_tag + backend
    env['DenseBackend'] = backend
    env['storage_tensor_headers'] = []
    if density != 'Sparse':
        env['storage_tensor_headers'] = ['#include <c10/core/TensorImpl.h>']

    # used for generating switch logic for external functions
    tag = density_tag + backend + scalar_name
    env['TypeID'] = 'TypeID::' + tag
    top_env['type_ids'].append(tag + ',')

    if backend == 'CUDA':
        env['extra_cuda_headers'] = []
        env['extra_cuda_headers'].append('#include <ATen/DeviceGuard.h>')
        if options.rocm:
            env['th_headers'] = [
                '#include <THH/THH.h>',
                '#include <THH/THHTensor.hpp>',
                '#include <THHUNN/THHUNN.h>',
                '#undef THNN_',
                '#undef THCIndexTensor_',
            ]
            env['extra_cuda_headers'].append('#include <ATen/hip/ATenHIPGeneral.h>')
            env['extra_cuda_headers'].append('#include <ATen/hip/HIPDevice.h>')
            env['extra_cuda_headers'].append('#include <ATen/hip/HIPTypeDefault.h>')
        else:
            env['th_headers'] = [
                '#include <THC/THC.h>',
                '#include <THC/THCTensor.hpp>',
                '#include <THCUNN/THCUNN.h>',
                '#undef THNN_',
                '#undef THCIndexTensor_',
            ]
            env['extra_cuda_headers'].append('#include <ATen/cuda/ATenCUDAGeneral.h>')
            env['extra_cuda_headers'].append('#include <ATen/cuda/CUDADevice.h>')
            env['extra_cuda_headers'].append('#include <ATen/cuda/CUDATypeDefault.h>')
        sname = '' if scalar_name == "Float" else scalar_name
        env['THType'] = 'Cuda{}'.format(sname)
        env['THStorage'] = 'THCuda{}Storage'.format(sname)
        env['THTensor'] = 'THCuda{}Tensor'.format(sname)
        env['THIndexTensor'] = 'THCudaLongTensor'
        env['state'] = ['globalContext().getTHCState()']
        env['isCUDA'] = 'true'
        env['storage_device'] = 'return storage->device;'
        env['Generator'] = 'CUDAGenerator'
    else:
        env['th_headers'] = [
            '#include <TH/TH.h>',
            '#include <TH/THTensor.hpp>',
            '#include <THNN/THNN.h>',
            '#undef THNN_',
        ]
        env['extra_cuda_headers'] = []
        env['THType'] = scalar_name
        env['THStorage'] = "TH{}Storage".format(scalar_name)
        env['THTensor'] = 'TH{}Tensor'.format(scalar_name)
        env['THIndexTensor'] = 'THLongTensor'
        env['state'] = []
        env['isCUDA'] = 'false'
        env['storage_device'] = 'throw std::runtime_error("CPU storage has no device");'
        env['Generator'] = 'CPUGenerator'
    env['AS_REAL'] = env['ScalarType']
    if scalar_name == "Half":
        env['SparseTensor'] = 'Tensor'
        if backend == "CUDA":
            env['AS_REAL'] = 'convert<at::Half,double>'

    declarations, definitions = function_wrapper.create_derived(
        env, declarations)
    env['type_derived_method_declarations'] = declarations
    env['type_derived_method_definitions'] = definitions

    fm = file_manager
    if env['DenseBackend'] == 'CUDA':
        fm = cuda_file_manager

    if density != 'Sparse':
        fm.write(env['Type'] + ".cpp", TYPE_DERIVED_CPP, env)
    else:
        fm.write(env['Type'] + ".cpp", SPARSE_TYPE_DERIVED_CPP, env)
    fm.write(env['Type'] + ".h", TYPE_DERIVED_H, env)

    type_register = TYPE_REGISTER.substitute(backend=env['Backend'], scalar_type=scalar_name, type_name=env['Type'])
    if env['DenseBackend'] == 'CPU':
        top_env['cpu_type_registrations'].append(type_register)
        top_env['cpu_type_headers'].append(
            '#include "ATen/{}.h"'.format(env['Type']))
    else:
        assert env['DenseBackend'] == 'CUDA'
        top_env['cuda_type_registrations'].append(type_register)
        top_env['cuda_type_headers'].append(
            '#include "ATen/{}.h"'.format(env['Type']))


def generate_type_extension_backend(backend, declarations):
    env = {}
    env['Type'] = "{}Type".format(backend)
    env['Backend'] = backend
    env['DeviceType'] = backend

    declarations, definitions = function_wrapper.create_extension_backend(
        env, declarations)
    env['type_method_declarations'] = declarations
    env['type_method_definitions'] = definitions

    file_manager.write(env['Type'] + ".cpp", TYPE_EXTENSION_CPP, env)
    file_manager.write(env['Type'] + ".h", TYPE_EXTENSION_H, env)

    extension_backend_register_switch = EXTENSION_BACKEND_REGISTER_SWITCH.substitute(env)
    top_env['extension_backend_register_switches'].append(extension_backend_register_switch)
    top_env['extension_backend_headers'].append(
        '#include <ATen/{}.h>'.format(env['Type']))


def generate_type_extension_backend_derived_types(backend):
    env = {}
    env['Backend'] = backend
    for scalar_name, c_type, _, _, _ in scalar_types:
        env['Type'] = "{}{}Type".format(backend, scalar_name)
        env['ScalarName'] = scalar_name
        env['ScalarType'] = c_type
        env['TypeID'] = 'TypeID::' + backend + scalar_name
        top_env['type_ids'].append(backend + scalar_name + ',')

        type_register = TYPE_REGISTER.substitute(backend=env['Backend'], scalar_type=scalar_name, type_name=env['Type'])
        top_env['cpu_type_registrations'].append(type_register)
        file_manager.write(env['Type'] + ".cpp", TYPE_EXTENSION_DERIVED_CPP, env)
        file_manager.write(env['Type'] + ".h", TYPE_EXTENSION_DERIVED_H, env)

        top_env['cpu_type_headers'].append('#include "ATen/{}.h"'.format(env['Type']))


def generate_legacy_th_dispatcher(backend, density, scalar_type, declarations):
    assert density == 'Dense'
    scalar_name, c_type, accreal, th_scalar_type, is_floating_type = scalar_type
    env = {}
    env['Backend'] = backend
    env['Dispatcher'] = "LegacyTH{}{}Dispatcher".format(backend, scalar_name)

    fm = file_manager
    if backend == 'CUDA':
        fm = cuda_file_manager

    fm.write(env['Dispatcher'] + ".cpp", LEGACY_TH_DISPATCHER_DERIVED_CPP, env)
    fm.write(env['Dispatcher'] + ".h", LEGACY_TH_DISPATCHER_DERIVED_H, env)

    return env


def iterate_types():
    for backend in backends:
        for density in densities:
            for scalar_type in scalar_types:
                if density == 'Mkldnn' and (backend != 'CPU' or scalar_type[0] != 'Float'):
                    continue
                if density == 'Sparse' and scalar_type[0] == 'Half':
                    # THS does not do half type yet.
                    continue
                yield (backend, density, scalar_type)


###################
# declare what files will be output _before_ we do any work
# so that the script runs quickly when we are just querying the
# outputs
def declare_outputs():
    core_files = ['Type.h', 'Tensor.h', 'TensorMethods.h']
    for f in core_files:
        core_file_manager.will_write(f)
    files = ['Declarations.yaml', 'TypeExtendedInterface.h', 'TypeDefault.cpp', 'TypeDefault.h',
             'LegacyTHDispatcher.h', 'LegacyTHDispatcher.cpp', 'LegacyTHFunctions.h',
             'Functions.h', 'NativeFunctions.h', 'RegisterCPU.cpp', 'RegisterCPU.h', 'ExtensionBackendRegistration.h']
    for f in files:
        file_manager.will_write(f)
    cuda_files = ['RegisterCUDA.cpp', 'RegisterCUDA.h']
    for f in cuda_files:
        cuda_file_manager.will_write(f)
    for fname in sorted(generators.keys()):
        fm = file_manager
        if generators[fname]['name'] == 'CUDA':
            fm = cuda_file_manager
        fm.will_write(fname)
    for backend, density, scalar_type in iterate_types():
        scalar_name = scalar_type[0]
        full_backend = backend if density == "Dense" else density + backend
        fm = file_manager
        if backend == 'CUDA':
            fm = cuda_file_manager
        for kind in ["Type"]:
            if kind != 'Type' and density == "Sparse":
                # No Storage or Tensor for sparse
                continue
            fm.will_write("{}{}{}.h".format(full_backend, scalar_name, kind))
            fm.will_write("{}{}{}.cpp".format(full_backend, scalar_name, kind))
        # output LegacyTHDispatchers
        if density == 'Dense':
            fm.will_write("{}{}{}{}.h".format('LegacyTH', full_backend, scalar_name, 'Dispatcher'))
            fm.will_write("{}{}{}{}.cpp".format('LegacyTH', full_backend, scalar_name, 'Dispatcher'))
    for backend in extension_backends:
        file_manager.will_write("{}Type.h".format(backend))
        file_manager.will_write("{}Type.cpp".format(backend))
        for scalar_type in scalar_types:
            scalar_name = scalar_type[0]
            file_manager.will_write("{}{}Type.h".format(backend, scalar_name))
            file_manager.will_write("{}{}Type.cpp".format(backend, scalar_name))


def filter_by_extension(files, *extensions):
    filtered_files = []
    for file in files:
        for extension in extensions:
            if file.endswith(extension):
                filtered_files.append(file)
    return filtered_files


# because EOL may not be LF(\n) on some environment (e.g. Windows),
# normalize EOL from CRLF/CR to LF and compare both files.
def cmpfiles_with_eol_normalization(a, b, names):
    results = ([], [], [])    # match, mismatch, error
    for x in names:
        try:
            with open(os.path.join(a, x)) as f:
                ax = f.read().replace('\r\n', '\n').replace('\r', '\n')
            with open(os.path.join(b, x)) as f:
                bx = f.read().replace('\r\n', '\n').replace('\r', '\n')
            if ax == bx:
                results[0].append(x)
            else:
                results[1].append(x)
        except OSError:
            results[2].append(x)
    return results


def generate_outputs():
    cwrap_files = filter_by_extension(options.files, '.cwrap')
    nn_files = filter_by_extension(options.files, 'nn.yaml', '.h')
    native_files = filter_by_extension(options.files, 'native_functions.yaml')

    declarations = [d
                    for file in cwrap_files
                    for d in cwrap_parser.parse(file)]

    declarations += nn_parse.run(nn_files)
    declarations += native_parse.run(native_files)
    declarations = preprocess_declarations.run(declarations)
    for fname, env in generators.items():
        fm = file_manager
        if env['name'] == 'CUDA':
            fm = cuda_file_manager
        fm.write(fname, GENERATOR_DERIVED, env)

    # note: this will fill in top_env['type/tensor_method_declarations/definitions']
    # and modify the declarations to include any information that will all_backends
    # be used by function_wrapper.create_derived
    output_declarations = function_wrapper.create_generic(top_env, declarations)
    output_declarations = postprocess_output_declarations(output_declarations)
    file_manager.write("Declarations.yaml", format_yaml(output_declarations))

    for backend, density, scalar_type in iterate_types():
        generate_storage_type_and_tensor(backend, density, scalar_type, declarations)
    for backend in extension_backends:
        generate_type_extension_backend(backend, declarations)
        generate_type_extension_backend_derived_types(backend)

    for backend, density, scalar_type in iterate_types():
        if density == 'Dense':
            generate_legacy_th_dispatcher(backend, density, scalar_type, [])

    core_files = {
        'Type.h': TYPE_H,
        'Tensor.h': TENSOR_H,
        'TensorMethods.h': TENSOR_METHODS_H
    }

    for core_file, core_template_file in core_files.items():
        core_file_manager.write(core_file, core_template_file, top_env)

    file_manager.write('TypeExtendedInterface.h', TYPE_EXTENDED_INTERFACE_H, top_env)
    file_manager.write('TypeDefault.h', TYPE_DEFAULT_H, top_env)
    file_manager.write('TypeDefault.cpp', TYPE_DEFAULT_CPP, top_env)

    file_manager.write('LegacyTHDispatcher.h', LEGACY_TH_DISPATCHER_H, top_env)
    file_manager.write('LegacyTHDispatcher.cpp', LEGACY_TH_DISPATCHER_CPP, top_env)

    file_manager.write('RegisterCPU.h', REGISTER_CPU_H, top_env)
    file_manager.write('RegisterCPU.cpp', REGISTER_CPU_CPP, top_env)

    cuda_file_manager.write('RegisterCUDA.h', REGISTER_CUDA_H, top_env)
    cuda_file_manager.write('RegisterCUDA.cpp', REGISTER_CUDA_CPP, top_env)

    file_manager.write('Functions.h', FUNCTIONS_H, top_env)
    file_manager.write('LegacyTHFunctions.h', LEGACY_TH_FUNCTIONS_H, top_env)

    file_manager.write('NativeFunctions.h', NATIVE_FUNCTIONS_H, top_env)

    file_manager.write('ExtensionBackendRegistration.h', EXTENSION_BACKEND_REGISTRATION_H, top_env)

    file_manager.check_all_files_written()
    cuda_file_manager.check_all_files_written()

    # check that generated files match source files
    core_source_path = os.path.join(options.source_path, 'core')
    match, mismatch, errors = cmpfiles_with_eol_normalization(core_install_dir, core_source_path, core_files.keys())
    if errors:
        raise RuntimeError("Error while trying to compare source and generated files for {}. "
                           "Source directory: {}.  Generated directory: {}."
                           .format(errors, core_source_path, core_install_dir))
    if mismatch:
        file_component = '{}'.format(','.join(mismatch))
        if len(mismatch) > 1:
            file_component = '{' + file_component + '}'
        update_cmd = "cp {}/{} {}".format(core_install_dir, file_component, core_source_path)
        raise RuntimeError("Source files: {} did not match generated files.  To update the source files, "
                           "set environment variable GEN_TO_SOURCE or run \"{}\"".format(mismatch, update_cmd))

declare_outputs()
if options.output_dependencies is not None:
    file_manager.write_outputs(options.output_dependencies)
    core_file_manager.write_outputs(options.output_dependencies + "-core")
    cuda_file_manager.write_outputs(options.output_dependencies + "-cuda")
else:
    generate_outputs()
