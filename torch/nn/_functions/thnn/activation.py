import torch
from torch.autograd.function import Function, InplaceFunction
from torch._thnn import type2backend
from torch.autograd.variable import Variable

from . import _all_functions


class PReLU(Function):
    @staticmethod
    def forward(ctx, input, weight):
        ctx._backend = type2backend[type(input)]
        output = input.new()
        ctx.num_parameters = weight.numel()
        if ctx.num_parameters == 1:
            ctx.num_parameters = 0
        ctx._backend.PReLU_updateOutput(
            ctx._backend.library_state,
            input,
            output,
            weight,
            ctx.num_parameters
        )
        ctx.save_for_backward(input, weight)
        return output

    @staticmethod
    def backward(ctx, grad_output):
        input, weight = ctx.saved_variables
        # alternatively, we could recalculate _backend, num_parameters
        return PReLUBackward.apply(input, weight, grad_output, ctx._backend, ctx.num_parameters)


class PReLUBackward(Function):
    @staticmethod
    def forward(ctx, input, weight, grad_output,backend, num_parameters):
        ctx.save_for_backward(input, weight, grad_output)
        ctx.num_parameters = num_parameters
        grad_input = input.new()
        backend.PReLU_updateGradInput(
            backend.library_state,
            input,
            grad_output,
            grad_input,
            weight,
            num_parameters
        )

        buf = weight.new()
        buf2 = weight.new()
        # TODO: this won't have to be zeroed in the future
        grad_weight = weight.new().resize_as_(weight).zero_()
        backend.PReLU_accGradParameters(
            backend.library_state,
            input,
            grad_output,
            grad_input,
            weight,
            grad_weight,
            buf,
            buf2,
            num_parameters,
            1
        )
        return grad_input, grad_weight

    @staticmethod
    def backward(ctx, ggI, ggW):
        input, weight, gO = ctx.saved_variables
        positive_mask = (input > 0).type_as(ggI)
        nonpositive_mask = (input <= 0).type_as(ggW)
        # Explanation: Let input be i, weight be w, grad_output be gO.
        # f(i, w) = i  if i > 0
        #         = wi if i <= 0
        # df/dx * gO  = gO      if i > 0      df/dw * g0 = 0      if i > 0
        #             = g0 * w  if i <= 0                = g0 * i  if i <= 0
        # The rest is taking derivatives of these wrt i, w, gO and summing/expanding properly.
        if ctx.num_parameters == 0:
            mask = positive_mask + nonpositive_mask * weight.expand_as(input)
            ggO = ggI * mask + ggW.expand_as(gO) * (nonpositive_mask * input)
            return ggW.expand_as(gO) * gO * nonpositive_mask, (ggI * gO * nonpositive_mask).sum(), ggO, None, None
        else:
            # Expand ggW to match size of ggI and weight to the size of input;
            # a simple expand doesn't work because ggW/weight is the size of the
            # input channel (dim==1 unless there is only 1 dimension)
            dims_to_unsqueeze = max(input.dim() - 2, 0)
            ggW_expanded = ggW
            weight_expanded = weight
            for _ in range(dims_to_unsqueeze):
                ggW_expanded = ggW_expanded.unsqueeze(1)
                weight_expanded = weight_expanded.unsqueeze(1)
            ggW_expanded = ggW_expanded.expand_as(ggI)
            weight_expanded = weight_expanded.expand_as(input)

            gI = ggW_expanded * gO * nonpositive_mask

            gW = ggI * gO * nonpositive_mask
            if input.dim() > 1:
                gW = gW.sum(0)
            while gW.dim() > 1:
                gW = gW.sum(1)

            mask = positive_mask + nonpositive_mask * weight_expanded
            ggO = ggI * mask + ggW_expanded * nonpositive_mask * input
            return gI, gW, ggO, None, None


class RReLU(InplaceFunction):

    def __init__(self, lower, upper, train, inplace=False):
        super(RReLU, self).__init__(inplace)
        self.lower = lower
        self.upper = upper
        self.train = train

    def forward(self, input):
        self._backend = type2backend[type(input)]
        if self.inplace:
            self.mark_dirty(input)
            output = input
        else:
            output = input.new(input.size())
        self.noise = input.new()
        self._backend.RReLU_updateOutput(
            self._backend.library_state,
            input,
            output,
            self.noise,
            self.lower,
            self.upper,
            self.train,
            self.inplace,
            torch.default_generator if not input.is_cuda else 0
        )
        self.save_for_backward(input)
        return output

    def backward(self, grad_output):
        input, = self.saved_tensors
        grad_input = input.new()
        self._backend.RReLU_updateGradInput(
            self._backend.library_state,
            input,
            grad_output,
            grad_input,
            self.noise,
            self.lower,
            self.upper,
            self.train,
            False
        )
        return grad_input


class SELU(InplaceFunction):
    alpha = 1.6732632423543772848170429916717
    scale = 1.0507009873554804934193349852946

    @staticmethod
    def forward(ctx, input, inplace):
        backend = type2backend[type(input)]
        if inplace:
            ctx.mark_dirty(input)
            output = input
        else:
            output = input.new(input.size())
        backend.ELU_updateOutput(
            backend.library_state,
            input,
            output,
            SELU.alpha,
            inplace,
        )
        output.mul_(SELU.scale)
        ctx.save_for_backward(input, output)
        return output

    @staticmethod
    def backward(ctx, grad_output):
        input, output = ctx.saved_variables
        if grad_output.volatile:
            grad_input = Variable(input.data.new(input.size()), volatile=True)
            backend = type2backend[type(input.data)]
            backend.ELU_updateGradInput(
                backend.library_state,
                input.data,
                grad_output.data.mul(SELU.scale),
                grad_input.data,
                output.data.div(SELU.scale),
                SELU.alpha,
                False
            )
        else:
            positive_mask = (output > 0).type_as(grad_output)
            negative_mask = (output <= 0).type_as(grad_output)
            grad_input = grad_output * SELU.scale * (positive_mask +
                                                     negative_mask * (output / SELU.scale + SELU.alpha))
        return grad_input, None


class Softmin(Function):

    def forward(self, input):
        self._backend = type2backend[type(input)]
        self.mininput = input.clone().mul(-1)
        output = input.new()
        self._backend.SoftMax_updateOutput(
            self._backend.library_state,
            self.mininput,
            output
        )
        self.save_for_backward(output)
        return output

    def backward(self, grad_output):
        output, = self.saved_tensors
        grad_input = grad_output.new()
        self._backend.SoftMax_updateGradInput(
            self._backend.library_state,
            self.mininput,
            grad_output,
            grad_input,
            output
        )
        return grad_input.mul(-1)


# TODO: This class should be removed once THNN function support Variable backward
class Threshold(Function):

    @staticmethod
    def forward(ctx, input, threshold, value, inplace):
        if inplace:
            if value > threshold:
                raise RuntimeError('in-place processing requires value ({}) to not '
                                   'exceed threshold ({})'.format(value, threshold))
        ctx.threshold = threshold
        ctx.value = value
        ctx.inplace = inplace

        if inplace:
            ctx.mark_dirty(input)
            output = input
        else:
            output = input.new(input.size())
        ctx.save_for_backward(input)

        backend = type2backend[type(input)]
        backend.Threshold_updateOutput(
            backend.library_state,
            input,
            output,
            threshold,
            value,
            inplace
        )
        return output

    @staticmethod
    def backward(ctx, grad_output):
        input, = ctx.saved_variables
        if grad_output.volatile:
            grad_input = Variable(input.data.new(input.size()), volatile=True)
            backend = type2backend[type(input.data)]
            backend.Threshold_updateGradInput(
                backend.library_state,
                input.data,
                grad_output.data,
                grad_input.data,
                ctx.threshold,
                ctx.value,
                False
            )
        else:
            grad_input = grad_output.masked_fill(input <= ctx.threshold, 0)
        return grad_input, None, None, None


# TODO: This class should be removed once THNN function support Variable backward
class LeakyReLU(Function):

    @staticmethod
    def forward(ctx, input, negative_slope, inplace):
        ctx.negative_slope = negative_slope
        ctx.inplace = inplace

        if inplace:
            ctx.mark_dirty(input)
            output = input
        else:
            output = input.new(input.size())
        ctx.save_for_backward(input)

        backend = type2backend[type(input)]
        backend.LeakyReLU_updateOutput(
            backend.library_state,
            input,
            output,
            negative_slope,
            inplace
        )
        return output

    @staticmethod
    def backward(ctx, grad_output):
        input, = ctx.saved_variables
        if grad_output.volatile:
            grad_input = Variable(input.data.new(input.size()), volatile=True)
            backend = type2backend[type(input.data)]
            backend.LeakyReLU_updateGradInput(
                backend.library_state,
                input.data,
                grad_output.data,
                grad_input.data,
                ctx.negative_slope,
                False
            )
        else:
            positive_mask = input > 0
            negative_mask = input <= 0
            mask = positive_mask.type_as(grad_output) + negative_mask.type_as(grad_output) * ctx.negative_slope
            grad_input = mask * grad_output
        return grad_input, None, None

_all_functions.append(PReLU)
_all_functions.append(PReLUBackward)
_all_functions.append(RReLU)
_all_functions.append(SELU)
_all_functions.append(Softmin)
_all_functions.append(Threshold)
_all_functions.append(LeakyReLU)
