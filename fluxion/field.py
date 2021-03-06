from collections import defaultdict

from .symbolic import *
from .tools import multimethod

import numpy


class PropagationDimension(Symbol):

    def __init__(self, name):
        super(PropagationDimension, self).__init__(name, real=True)
        self.name = name

    def _canonical_args(self):
        return (self.name,), None


class TransverseDimension(Symbol):

    def __init__(self, name, grid, uniform=False):
        super(TransverseDimension, self).__init__(name, real=True)
        # TODO: we need to actually check for uniformity instead of relying on the user
        self.name = name
        self.grid = numpy.array(grid)
        self.uniform = uniform
        if uniform:
            self.grid_step = self.grid[1] - self.grid[0]

    @classmethod
    def uniform(cls, name, start, stop, points, endpoint=False):
        return TransverseDimension(
            name, numpy.linspace(start, stop, points, endpoint=endpoint), uniform=True)

    def _canonical_args(self):
        return (self.name,), None


def momentum_space(dim, name=''):
    assert isinstance(dim, TransverseDimension)
    assert dim.uniform
    new_grid = numpy.fft.fftfreq(dim.grid.size, dim.grid[1] - dim.grid[0])
    new_grid = numpy.fft.fftshift(new_grid)
    return TransverseDimension(name, new_grid, uniform=True)


def to_momentum_space(field, *dimensions):
    if len(dimensions) == 0:
        dimensions = field.dimensions

    kdims = {dim: momentum_space(dim) for dim in dimensions}

    axes = [field.dimensions.index(dim) for dim in dimensions]

    dV = 1
    size = 1
    for dim in dimensions:
        dV *= dim.grid_step
        size *= dim.grid.size

    fft_scale = (dV / size)**0.5
    new_data = numpy.fft.fftn(field.data, axes=axes) * fft_scale
    new_data = numpy.fft.fftshift(new_data, axes=axes)
    new_dimensions = [kdims.get(dim, dim) for dim in field.dimensions]

    kdims_list = [kdims[dim] for dim in dimensions]

    return [Field('_momentum_space', *new_dimensions, data=new_data)] + kdims_list


class TransverseIntegerDimension(Symbol):

    def __init__(self, name, start, stop, points):
        super(TransverseDimension, self).__init__(name, real=True)
        self.__name = name
        self.__params = (start, stop)
        self.grid = numpy.arange(start, stop + 1)

    def _canonical_args(self):
        return (self.__name,) + self.__params, None


# Field kinds
REAL = 'real'
COMPLEX = 'complex'


class UnknownField(Symbol):

    def __init__(self, name, *dimensions, kind=REAL):
        super(UnknownField, self).__init__(name)
        self.__name = name
        self.dimensions = dimensions
        self.kind = kind

    def without_dimensions(self, *dims):
        new_dims = [dim for dim in self.dimensions if dim not in dims]
        return UnknownField(self.__name, *new_dims, kind=self.kind)

    def _canonical_args(self):
        return (self.__name,) + self.dimensions, None

    def __call__(self, *exprs):
        # check that exprs are compatible with dimensions
        return Apply(self, *exprs)


class Noise(Symbol):

    def __init__(self, name, *dimensions, real=False, complex=True):
        super(Noise, self).__init__(name, real=real, complex=complex)
        self.__name = name
        self.dimensions = dimensions

    def _canonical_args(self):
        return (self.__name,) + self.dimensions, None


SCALAR_TYPES = (int, float, complex)
SCALAR_KINDS = {
    int: REAL,
    float: REAL,
    complex: COMPLEX
}
DTYPE_KINDS = {
    'i': REAL,
    'f': REAL,
    'c': COMPLEX
}
DEFAULT_DTYPES = {
    REAL: numpy.float64,
    COMPLEX: numpy.complex128
}


class Field(Symbol):

    def __init__(self, name, *dimensions, data=None, kind=None):
        super(Field, self).__init__(name)
        self.__name = name
        self.dimensions = dimensions

        if kind is None:
            if data is None:
                self.kind = COMPLEX
            elif isinstance(data, (numpy.ndarray, numpy.number)):
                self.kind = DTYPE_KINDS[data.dtype.kind]
            elif isinstance(data, SCALAR_TYPES):
                self.kind = SCALAR_KINDS[type(data)]
        else:
            assert kind in (REAL, COMPLEX)
            self.kind = kind

        dtype = DEFAULT_DTYPES[self.kind]
        shape = tuple(d.grid.size for d in dimensions)

        if data is None:
            self.data = numpy.empty(shape, dtype)
        elif isinstance(data, SCALAR_TYPES):
            self.data = numpy.ones(shape, dtype) * numpy.array(data).astype(dtype)
        elif isinstance(data, numpy.ndarray):
            assert data.shape == shape
            assert numpy.can_cast(data.dtype, dtype)
            self.data = data.astype(dtype)
        else:
            raise ValueError

    def _canonical_args(self):
        return (self.__name,) + self.dimensions, None

    def __call__(self, *exprs):
        # check that exprs are compatible with dimensions
        return Apply(self, *exprs)


def as_field(obj, template=None):
    """
    need to be able to:

    psi0 = as_field(x**2) # creates a 1D field psi0(x) = x**2
    psi0 = as_field(x**2, x, y) # creates a 2D field psi0(x, y) = x**2
    psi0 = as_field(1) # creates a 0D field?
    psi0 = as_field(1, x, y) # creates a 2D field psi0(x, y) = 1

    psi = field(x)
    psi0 = as_field(psi, x, y) # creates a 2D field psi0(x, y) = psi(x)
    """
    if template is None:
        if obj is None or isinstance(obj, SCALAR_TYPES + (numpy.ndarray,)):
            return Field('', data=obj)
        elif isinstance(obj, Field):
            return obj
        elif isinstance(obj, Expr):
            vs = used_variables(obj)
            dimensions = list(sorted(vs['transverse_dimensions']))
            return Field('', *dimensions, data=as_array(obj, dimensions))
    else:
        return Field(
            '', *template.dimensions,
            data=as_array(obj, template.dimensions, template.kind), kind=template.kind)


def join(dicts):
    result = defaultdict(lambda: set())
    for d in dicts:
        for k, v in d.items():
            result[k] = result[k].union(v)
    return dict(result)


@multimethod
def _used_variables(expr: (list, tuple)):
    return join([_used_variables(elem) for elem in expr])

@multimethod
def _used_variables(expr: ExprNode):
    return _used_variables(expr.args)

@multimethod
def _used_variables(expr: Field):
    return _used_variables(expr.dimensions)

@multimethod
def _used_variables(expr: Differential):
    return join([
        dict(differentials=set([expr])),
        _used_variables(expr.args)])

@multimethod
def _used_variables(expr: ExprLeaf):
    return {}

@multimethod
def _used_variables(expr: TransverseDimension):
    return dict(transverse_dimensions=set([expr]))

@multimethod
def _used_variables(expr: PropagationDimension):
    return dict(propagation_dimensions=set([expr]))

@multimethod
def _used_variables(expr: Noise):
    return join(
        [dict(noises=set([expr]))]
        + [_used_variables(dim) for dim in expr.dimensions])


def used_variables(expr):
    return join([
        _used_variables(expr),
        dict(
            noises=set(), propagation_dimensions=set(),
            transverse_dimensions=set(), differentials=set())])


def as_array(obj, dimensions=None, kind=None):

    if dimensions is None:
        if isinstance(obj, Field):
            dimensions = obj.dimensions
        elif isinstance(obj, Expr):
            vs = used_variables(obj)
            tds = vs.get('transverse_dimensions', [])
            dimensions = list(sorted(tds, key=lambda dim: dim.name))
        else:
            dimensions = ()

    arr = _as_array(obj, dimensions)

    if kind is None:
        kind = DTYPE_KINDS[arr.dtype.kind]

    dtype = DEFAULT_DTYPES[kind]
    arr = arr.astype(dtype)

    tile = [d.grid.size // arr_size for d, arr_size in zip(dimensions, arr.shape)]
    return numpy.tile(arr, tile)


@multimethod
def _as_array(obj: type(None), dimensions):
    shape = tuple(d.grid.size for d in dimensions)
    return numpy.empty(shape)

@multimethod
def _as_array(obj: SCALAR_TYPES, dimensions):
    shape = tuple(d.grid.size for d in dimensions)
    return numpy.ones(shape) * obj

@multimethod
def _as_array(obj: numpy.ndarray, dimensions):
    shape = tuple(d.grid.size for d in dimensions)
    assert obj.shape == shape
    return obj

@multimethod
def _as_array(obj: Add, dimensions):
    return _as_array(obj.args[0], dimensions) + _as_array(obj.args[1], dimensions)

@multimethod
def _as_array(obj: Sub, dimensions):
    return _as_array(obj.args[0], dimensions) - _as_array(obj.args[1], dimensions)

@multimethod
def _as_array(obj: Mul, dimensions):
    return _as_array(obj.args[0], dimensions) * _as_array(obj.args[1], dimensions)

@multimethod
def _as_array(obj: Div, dimensions):
    return _as_array(obj.args[0], dimensions) / _as_array(obj.args[1], dimensions)

@multimethod
def _as_array(obj: Pow, dimensions):
    return _as_array(obj.args[0], dimensions) ** _as_array(obj.args[1], dimensions)

@multimethod
def _as_array(obj: Apply, dimensions):
    func = obj.args[0]
    assert isinstance(func, Function)
    return func.evaluate(*[_as_array(arg, dimensions) for arg in obj.args[1:]])

@multimethod
def _as_array(obj: Field, dimensions):
    return rearrange_dims(obj.data, obj.dimensions, dimensions)

@multimethod
def _as_array(obj: Scalar, dimensions):
    return _as_array(obj.value, dimensions)

@multimethod
def _as_array(obj: TransverseDimension, dimensions):
    return rearrange_dims(obj.grid, [obj], dimensions)


def rearrange_dims(arr, arr_dims, target_dims):

    if len(target_dims) == 0:
        return arr

    # transpose the array so that the order of its dimensions
    # is the same as in `target_dims`
    to_sort = [(target_dims.index(dim), i) for i, dim in enumerate(arr_dims)]
    to_transpose = [i for _, i in sorted(to_sort)]
    arr = arr.transpose(*to_transpose)

    # reshape the array adding new array dimensions (of size 1)
    # in place of unused array dimensions
    to_reshape = [dim.grid.size if dim in arr_dims else 1 for dim in target_dims]
    return arr.reshape(*to_reshape)


@multimethod
def substitute(expr: ExprNode, to_sub):
    return type(expr)(*[substitute(arg, to_sub) for arg in expr.args])

@multimethod
def substitute(expr: (UnknownField, PropagationDimension, Differential), to_sub):
    return to_sub[expr]

@multimethod
def substitute(expr: ExprLeaf, to_sub):
    return expr


def find_generic_field(fields, preferred_dim_order):
    if any(field.kind == COMPLEX for field in fields):
        kind = COMPLEX
    else:
        kind = REAL

    preferred_dims = set(preferred_dim_order)
    used_dims = set()
    for field in fields:
        used_dims.update(field.dimensions)

    used_dims_not_in_pd = used_dims - preferred_dims

    generic_dims = (
        [dim for dim in preferred_dim_order if dim in used_dims]
        + [dim for dim in used_dims_not_in_pd])
    return UnknownField('', *generic_dims, kind=kind)


def join_fields(fields, new_dimension, new_dimension_grid, generic_field):
    assert new_dimension not in generic_field.dimensions
    assert isinstance(new_dimension, PropagationDimension)

    # FIXME: setting uniform=True for the time being to make plotting easier
    new_dim = TransverseDimension(new_dimension.name, new_dimension_grid, uniform=True)

    # Currently we're just attaching the new dimension in front,
    # but it is possible to preserve the position it has in the original field.
    new_field = Field('', new_dim, *generic_field.dimensions, kind=generic_field.kind)

    for i, field in enumerate(fields):
        new_field.data[i] = field.data

    return new_field
