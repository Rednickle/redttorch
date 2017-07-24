#include "batch_normalization.h"

#include "torch/csrc/autograd/variable.h"
#include "torch/csrc/autograd/functions/utils.h"
#include "torch/csrc/autograd/functions/basic_ops.h"
#include "torch/csrc/nn/THNN_generic.h"
#include "torch/csrc/utils/auto_gpu.h"
#include "torch/csrc/autograd/python_function.h"
#include "torch/csrc/utils/auto_gil.h"
#include "torch/csrc/autograd/python_variable.h"

#include <sstream>

#ifdef WITH_CUDNN
#include "torch/csrc/cudnn/BatchNorm.h"
#include "torch/csrc/cudnn/Handles.h"
#include "torch/csrc/cudnn/Types.h"
extern THCState* state;
#endif

namespace {
    void check_dims_match_num_input_features(const std::string& arg_name, long expected, long actual){
      if (actual != expected){
        std::stringstream ss;
        ss << arg_name << " should contain " << expected << " elements not " << actual ;
        throw std::runtime_error(ss.str());
      }
    }
}

namespace torch { namespace autograd {

using thpp::Tensor;

#ifndef CUDNN_BN_MIN_EPSILON
#define CUDNN_BN_MIN_EPSILON 0
#endif

auto BatchNormForward::apply(const variable_list& inputs) -> variable_list {
  check_input_variables("BatchNorm", inputs, 3, 1);
  
  auto& input = inputs[0];
  auto& weight = inputs[1];
  auto& bias = inputs[2];
  AutoGPU guard(input->data->getDevice());
   
  auto num_features = input->data->rawSizes()[1];
  check_dims_match_num_input_features("running_mean", num_features, running_mean->numel());
  check_dims_match_num_input_features("running_var", num_features, running_var->numel());
  if (weight){
    check_dims_match_num_input_features("weight", num_features, weight->data->numel());
  }
  if (bias){
    check_dims_match_num_input_features("bias", num_features, bias->data->numel());
  }

  bool use_cudnn = false;
#ifdef WITH_CUDNN
  use_cudnn = (input->data->isCuda()
               && input->data->type() != thpp::Type::HALF
               && weight && bias
               && cudnn_enabled && CUDNN_VERSION >= 5110L);
#endif

  auto output = input->data->newTensor();
  output->resizeAs(*input->data);

  std::unique_ptr<Tensor> save_mean(output->newTensor());
  save_mean->resizeAs(*running_mean);
  std::unique_ptr<Tensor> save_std(output->newTensor());
  save_std->resizeAs(*running_var);

  if (use_cudnn && eps >= CUDNN_BN_MIN_EPSILON) {
#ifdef WITH_CUDNN
    torch::cudnn::cudnn_batch_norm_forward(
        state,
        torch::cudnn::getCudnnHandle(),
        torch::cudnn::getCudnnDataType(*input->data),
        (THVoidTensor*)input->data->cdata(),
        (THVoidTensor*)output->cdata(),
        (THVoidTensor*)weight->data->cdata(),
        (THVoidTensor*)bias->data->cdata(),
        (THVoidTensor*)running_mean->cdata(),
        (THVoidTensor*)running_var->cdata(),
        (THVoidTensor*)save_mean->cdata(),
        (THVoidTensor*)save_std->cdata(),
        training,
        momentum,
        eps);
#endif
  } else {
    torch::nn::BatchNormalization_updateOutput(
        input->data.get(),
        output.get(),
        weight ? weight->data.get() : nullptr,
        bias ? bias->data.get() : nullptr,
        running_mean.get(),
        running_var.get(),
        save_mean.get(),
        save_std.get(),
        training,
        momentum,
        eps);
  }

  auto outputs = as_tensor_list(std::move(output));
  return wrap_outputs(inputs, std::move(outputs), [&](FunctionFlags f) {
    return std::make_shared<BatchNormBackward>(
        f, *this, std::move(save_mean), std::move(save_std),
        input->save(this),
        //weight->save(this),
        //bias->save(this)
        Variable::save_opt(weight.get(), this),
        Variable::save_opt(bias.get(), this)
    );
  });
};

auto BatchNormBackward::apply(const variable_list& grad_outputs) -> variable_list {
  check_input_variables("BatchNormBackward", grad_outputs, 1);
  auto input_var = input_.unpack();
  auto weight_var = weight_.unpack();
  auto bias_var = bias_.unpack();

  std::unique_ptr<thpp::Tensor> input {input_var->data->clone_shallow()};
  std::unique_ptr<thpp::Tensor> weight {weight_var ? weight_var->data->clone_shallow() : nullptr};
  std::unique_ptr<thpp::Tensor> bias {bias_var ? bias_var->data->clone_shallow() : nullptr};

  AutoGPU guard(input->getDevice());

  bool use_cudnn = false;
#ifdef WITH_CUDNN
  use_cudnn = (input->isCuda()
               && input->type() != thpp::Type::HALF
               && weight && bias && training
               && cudnn_enabled && CUDNN_VERSION >= 5110L);
#endif

  std::unique_ptr<Tensor> grad_input;
  if (should_compute_output(0) || use_cudnn) {
    grad_input = input->newTensor();
    grad_input->resizeAs(*input);
  }

  std::unique_ptr<Tensor> grad_weight;
  if (should_compute_output(1) || use_cudnn) {
    grad_weight = weight->newTensor();
    grad_weight->resizeAs(*weight);
    if (!use_cudnn) {
      grad_weight->zero();
    }
  }

  std::unique_ptr<Tensor> grad_bias;
  if (should_compute_output(2) || use_cudnn) {
    grad_bias = bias->newTensor();
    grad_bias->resizeAs(*bias);
    if (!use_cudnn) {
      grad_bias->zero();
    }
  }

  auto grad_output = grad_outputs[0]->data->contiguous();

  if (use_cudnn && eps >= CUDNN_BN_MIN_EPSILON) {
#ifdef WITH_CUDNN
    torch::cudnn::cudnn_batch_norm_backward(
        state,
        torch::cudnn::getCudnnHandle(),
        torch::cudnn::getCudnnDataType(*input),
        (THVoidTensor*)input->cdata(),
        (THVoidTensor*)grad_output->cdata(),
        (THVoidTensor*)grad_input->cdata(),
        (THVoidTensor*)grad_weight->cdata(),
        (THVoidTensor*)grad_bias->cdata(),
        (THVoidTensor*)weight->cdata(),
        (THVoidTensor*)running_mean->cdata(),
        (THVoidTensor*)running_var->cdata(),
        (THVoidTensor*)save_mean_->cdata(),
        (THVoidTensor*)save_std_->cdata(),
        training,
        eps);
#endif
  } else {
    torch::nn::BatchNormalization_backward(
        input.get(),
        grad_output.get(),
        grad_input.get(),
        grad_weight.get(),
        grad_bias.get(),
        weight.get(),
        running_mean.get(),
        running_var.get(),
        save_mean_.get(),
        save_std_.get(),
        training,
        1.0,
        eps);
  }

  // Add saved variables used out of the pure autograd to inputs
  variable_list all_inputs(grad_outputs);
  all_inputs.push_back(input_var);
  auto outputs =  as_tensor_list(std::move(grad_input),
                                 std::move(grad_weight),
                                 std::move(grad_bias));
  
  bool affine = (weight.get() != nullptr);
  if (affine) {
    all_inputs.push_back(weight_var);
    all_inputs.push_back(bias_var);
    return wrap_outputs(all_inputs, std::move(outputs), [&](FunctionFlags f) {
      return std::make_shared<BatchNormBackwardBackward>(
        f, *this, std::move(save_mean_), std::move(save_std_),
        //input_var->save(this), Variable::save_opt(weight_var.get(), this),
        //input_var->save(this), Variable::save_opt(weight_var.get(), this),
        
        //Variable::save_opt(bias_var.get(), this), grad_outputs[0]->save(this));
        input_var->save(this), weight_var->save(this),
        Variable::save_opt(bias_var.get(), this), grad_outputs[0]->save(this));
      });
  } else {
    return wrap_outputs(all_inputs, std::move(outputs), [&](FunctionFlags f) {
      return std::make_shared<BatchNormBackwardBackward>(
        f, *this, std::move(save_mean_), std::move(save_std_),
        input_var->save(this), Variable::save_opt(weight_var.get(), this),
        Variable::save_opt(bias_var.get(), this), grad_outputs[0]->save(this));
      });
  }
};

auto BatchNormBackward::releaseVariables() -> void {
  input_.data.reset();
  weight_.data.reset();
  bias_.data.reset();
}


auto BatchNormBackwardBackward::apply(const variable_list& grad_grad_inputs) -> variable_list {
  check_input_variables("BatchNormBackwardBackward", grad_grad_inputs, 3, 0);
  auto ggI = grad_grad_inputs[0];
  auto ggW = grad_grad_inputs[1];
  auto ggb = grad_grad_inputs[2];
  printf("\ngrad stuff %p %p %p\n", ggI.get(), ggW.get(), ggb.get());

  auto gO = grad_output_.unpack();
  auto input_var = input_.unpack();
  auto weight_var = weight_.unpack();
  auto bias_var = bias_.unpack();

  //std::unique_ptr<thpp::Tensor> input {input_var->data->clone_shallow()};
  std::unique_ptr<thpp::Tensor> weight {weight_var ? weight_var->data->clone_shallow() : nullptr};
  std::unique_ptr<thpp::Tensor> bias {bias_var ? bias_var->data->clone_shallow() : nullptr};

  bool affine = (weight.get() != nullptr);
  //if (weight.get() != nullptr || bias.get() != nullptr) {
  //  throw std::runtime_error("BatchNormBackwardBackward does not currently support affine parameters");
  //}

  //auto M = input->sizes()[0];
  //auto mu = input->newTensor();
  //mu->sum(*input.get(), 0, 0);
  

  //mu->neg(*mu.get());
  //std::unique_ptr<thpp::Tensor> neg_mu_expanded(mu->newExpand(input->sizes()));

  //auto input_min_mu = input->newTensor();
  
//  def backback_no_affine(input, ggI, gO):
  printf("Callable? %d\n", PyCallable_Check(THPBatchNormBackwardBackwardFn));
  printf("BACKWARDBACKWARD FN %p\n", THPBatchNormBackwardBackwardFn);
  printf("eps? %lf\n", eps);
//  def backback_not_affine(input, gamma, ggI, ggG, ggB, gO, eps):

  //PyObject_CallFunctionObjArgs(THPBatchNormBackwardBackwardFn, input_, ggI, grad_output_);
  //PyObject_CallObject(THPBatchNormBackwardBackwardFn, Py_None);
  AutoGIL gil;
  //PyObject* args = PyTuple_Pack(1,PyFloat_FromDouble(2.0));
  PyObject *input_pvar = THPVariable_Wrap(input_var);
  PyObject *weight_pvar = weight.get() != nullptr ? THPVariable_Wrap(weight_var) : Py_None;
  PyObject *ggi_pvar = ggI.get() != nullptr ? THPVariable_Wrap(ggI) : Py_None;
  PyObject *ggW_pvar = ggW.get() != nullptr ? THPVariable_Wrap(ggW) : Py_None;
  PyObject *ggb_pvar = ggb.get() != nullptr ? THPVariable_Wrap(ggb) : Py_None;
  PyObject *gO_pvar = THPVariable_Wrap(gO);
  PyObject *eps_py = PyFloat_FromDouble(eps);
  Py_INCREF(input_pvar);
  if (ggi_pvar != Py_None) {
    Py_INCREF(ggi_pvar);
  }
  if (ggW_pvar != Py_None) {
    Py_INCREF(ggW_pvar);
  }
  if (ggb_pvar != Py_None) {
    Py_INCREF(ggb_pvar);
  }
  if (weight_pvar != Py_None) {
    Py_INCREF(weight_pvar);
  }
  Py_INCREF(gO_pvar);
  Py_INCREF(eps_py);
  PyObject* args = PyTuple_Pack(7, input_pvar, weight_pvar, ggi_pvar, ggW_pvar, ggb_pvar, gO_pvar, eps_py);
  PyObject* backback_ret = PyObject_CallObject(THPBatchNormBackwardBackwardFn, args);
  printf("got backback_ret %p\n", backback_ret);
  Py_INCREF(backback_ret);
  printf("got back tuple? %d\n", PyTuple_Check(backback_ret));
  printf("got back %ld\n", PyTuple_Size(backback_ret));
  printf("returning\n");
  PyObject *gI = ggI ? PyTuple_GET_ITEM(backback_ret, 0) : Py_None;
  PyObject *gG = ggW ? PyTuple_GET_ITEM(backback_ret, 1) : Py_None;
  PyObject *gb = ggb ? PyTuple_GET_ITEM(backback_ret, 2) : Py_None;
  PyObject *ggO = PyTuple_GET_ITEM(backback_ret, 3);
  printf("done getting items\n");
  //Py_INCREF(gI);
  //Py_INCREF(ggO);
  //if (affine) {
    //Py_INCREF(gG);
    //Py_INCREF(gb);
  //}
  
  //printf("done inc items %d %d %d %d\n", gI == Py_None, gG = Py_None, gb == Py_None, ggO == Py_None);
  //auto gI_var = ((THPVariable*)gI)->cdata;
  //auto ggO_var = ((THPVariable*)ggO)->cdata;
  if (affine) {
    //auto gG_var = ((THPVariable*)gG)->cdata;
    //gG_var = nullptr;
    //gb_var = nullptr;
    //auto gb_var = ((THPVariable*)gb)->cdata;
    //printf("done doing the cdata thing %p %p %p %p\n", ggI.get(), ggW.get(), ggb.get(), ggO_var.get());
    auto ggO_var = ggO == Py_None ? nullptr : ((THPVariable*)ggO)->cdata;
    auto gI_var  = gI == Py_None ? nullptr : ((THPVariable*)gI)->cdata;
    auto gG_var = gG == Py_None ? nullptr : ((THPVariable*)gG)->cdata;
    auto gB_var = gb == Py_None ? nullptr: ((THPVariable*)gb)->cdata;
    auto ret = {ggO_var, gI_var, gG_var, gB_var};
    printf("done doing the return!\n");
    return ret;
    //return {ggO_var, gI_var};
  } else {
    auto ggO_var = ggO == Py_None ? nullptr : ((THPVariable*)ggO)->cdata;
    auto gI_var = ((THPVariable*)gI)->cdata;
    return {ggO_var, gI_var};
  }
};

auto BatchNormBackwardBackward::releaseVariables() -> void {
  input_.data.reset();
  weight_.data.reset();
  bias_.data.reset();
  grad_output_.data.reset();
}


}} // namespace torch::autograd
