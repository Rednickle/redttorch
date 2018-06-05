#include "THCTensorTypeUtils.cuh"
#include "THCTensor.h"
#include "THCTensorCopy.h"
#include "THCHalf.h"
#include <stdlib.h>

namespace {

struct SizeAndStride {
  int64_t size;
  int64_t stride;
};

/* 
 A comparator that will sort SizeAndStride structs by stride,
 in ascending order.
 */
int compareSizeAndStride(const void* a, const void* b) {
  const SizeAndStride* aS = (const SizeAndStride*) a;
  const SizeAndStride* bS = (const SizeAndStride*) b;
  
  if (aS->stride < bS->stride) return -1;
  if (aS->stride == bS->stride) return 0;
  return 1;
}

}

#define IMPL_TENSOR_UTILS(TENSOR_TYPE, DATA_TYPE)                       \
                                                                        \
TENSOR_TYPE*                                                            \
TensorUtils<TENSOR_TYPE>::newTensor(THCState* state) {                  \
  return TENSOR_TYPE##_new(state);                                      \
}                                                                       \
                                                                        \
TENSOR_TYPE*                                                            \
TensorUtils<TENSOR_TYPE>::newContiguous(THCState* state,                \
                                        TENSOR_TYPE* t) {               \
  return TENSOR_TYPE##_newContiguous(state, t);                         \
}                                                                       \
                                                                        \
THLongStorage*                                                          \
TensorUtils<TENSOR_TYPE>::newSizeOf(THCState* state,                    \
                                    TENSOR_TYPE* t) {                   \
  return TENSOR_TYPE##_newSizeOf(state, t);                             \
}                                                                       \
                                                                        \
void                                                                    \
TensorUtils<TENSOR_TYPE>::retain(THCState* state,                       \
                                 TENSOR_TYPE* t) {                      \
  TENSOR_TYPE##_retain(state, t);                                       \
}                                                                       \
                                                                        \
void                                                                    \
TensorUtils<TENSOR_TYPE>::free(THCState* state,                         \
                               TENSOR_TYPE* t) {                        \
  TENSOR_TYPE##_free(state, t);                                         \
}                                                                       \
                                                                        \
void                                                                    \
TensorUtils<TENSOR_TYPE>::freeCopyTo(THCState* state,                   \
                                     TENSOR_TYPE* src,                  \
                                     TENSOR_TYPE* dst) {                \
  TENSOR_TYPE##_freeCopyTo(state, src, dst);                            \
}                                                                       \
                                                                        \
void                                                                    \
TensorUtils<TENSOR_TYPE>::resize(THCState* state,                       \
                                 TENSOR_TYPE* out,                      \
                                 THLongStorage* sizes,                  \
                                 THLongStorage* strides) {              \
  TENSOR_TYPE##_resize(state, out, sizes, strides);                     \
}                                                                       \
                                                                        \
void                                                                    \
TensorUtils<TENSOR_TYPE>::resizeAs(THCState* state,                     \
                                   TENSOR_TYPE* dst,                    \
                                   TENSOR_TYPE* src) {                  \
  TENSOR_TYPE##_resizeAs(state, dst, src);                              \
}                                                                       \
                                                                        \
void                                                                    \
TensorUtils<TENSOR_TYPE>::squeeze1d(THCState *state,                    \
                                    TENSOR_TYPE *dst,                   \
                                    TENSOR_TYPE *src,                   \
                                    int dimension) {                    \
  TENSOR_TYPE##_squeeze1d(state, dst, src, dimension);                  \
}                                                                       \
                                                                        \
void                                                                    \
TensorUtils<TENSOR_TYPE>::unsqueeze1d(THCState *state,                  \
                                    TENSOR_TYPE *dst,                   \
                                    TENSOR_TYPE *src,                   \
                                    int dimension) {                    \
  TENSOR_TYPE##_unsqueeze1d(state, dst, src, dimension);                \
}                                                                       \
                                                                        \
DATA_TYPE*                                                              \
TensorUtils<TENSOR_TYPE>::getData(THCState* state,                      \
                                  TENSOR_TYPE* t) {                     \
  /* FIXME: no cast is required except for THCudaHalfTensor */          \
  return (DATA_TYPE*) TENSOR_TYPE##_data(state, t);                     \
}                                                                       \
                                                                        \
ptrdiff_t                                                               \
TensorUtils<TENSOR_TYPE>::getNumElements(THCState* state,               \
                                         TENSOR_TYPE* t) {              \
  return TENSOR_TYPE##_nElement(state, t);                              \
}                                                                       \
                                                                        \
int64_t                                                                 \
TensorUtils<TENSOR_TYPE>::getSize(THCState* state,                      \
                                  TENSOR_TYPE* t,                       \
                                  int dim) {                            \
  return TENSOR_TYPE##_size(state, t, dim);                             \
}                                                                       \
                                                                        \
int64_t                                                                 \
TensorUtils<TENSOR_TYPE>::getStride(THCState* state,                    \
                                    TENSOR_TYPE* t,                     \
                                    int dim) {                          \
  return TENSOR_TYPE##_stride(state, t, dim);                           \
}                                                                       \
                                                                        \
                                                                        \
bool                                                                    \
TensorUtils<TENSOR_TYPE>::isContiguous(THCState* state,                 \
                                       TENSOR_TYPE* t) {                \
  return TENSOR_TYPE##_isContiguous(state, t);                          \
}                                                                       \
                                                                        \
bool                                                                    \
TensorUtils<TENSOR_TYPE>::allContiguous(THCState* state,                \
                                        TENSOR_TYPE** inputs,           \
                                        int numInputs) {                \
  THAssert(numInputs > 0);                                                \
  for (int i = 0; i < numInputs; ++i) {                                 \
    if (!TensorUtils<TENSOR_TYPE>::isContiguous(state, inputs[i])) {    \
      return false;                                                     \
    }                                                                   \
  }                                                                     \
  return true;                                                          \
}                                                                       \
                                                                        \
/* Due to the resize semantics of ops with `out=` keywords, if       */ \
/* the output `tensor` has the same shape as the output of the       */ \
/* reduction operation, then any noncontiguities in the output       */ \
/* `tensor` should be preserved. This needs to be special cased b/c  */ \
/* otherwise, when keepdim=False, the implementations of reduction   */ \
/* ops resize `tensor` to the reduced size with keepdim=True, and    */ \
/* then later squeeze `tensor` to the correct output size, breaking  */ \
/* the contiguity guarantees of the resize semantics.                */ \
void                                                                    \
TensorUtils<TENSOR_TYPE>::preserveReduceDimSemantics(                   \
                          THCState *state, TENSOR_TYPE *tensor,         \
                          int in_dims, int64_t dimension, int keepdim) {\
  int out_dims = THCTensor_nDimension(state, tensor);                   \
  if (out_dims > 0 && !keepdim && out_dims == in_dims - 1) {            \
    TensorUtils<TENSOR_TYPE>::unsqueeze1d(state, tensor, tensor, dimension);\
  }                                                                     \
}                                                                       \
                                                                        \
int                                                                     \
TensorUtils<TENSOR_TYPE>::getDevice(THCState* state,                    \
                                    TENSOR_TYPE* t) {                   \
  return TENSOR_TYPE##_getDevice(state, t);                             \
}                                                                       \
                                                                        \
bool                                                                    \
TensorUtils<TENSOR_TYPE>::allSameDevice(THCState* state,                \
                                        TENSOR_TYPE** inputs,           \
                                        int numInputs) {                \
  THAssert(numInputs > 0);                                              \
  int device = TensorUtils<TENSOR_TYPE>::getDevice(state, inputs[0]);   \
  for (int i = 1; i < numInputs; ++i) {                                 \
    if (TensorUtils<TENSOR_TYPE>::getDevice(state, inputs[i]) != device) {     \
      return false;                                                     \
    }                                                                   \
  }                                                                     \
  return true;                                                          \
}                                                                       \
                                                                        \
void                                                                    \
TensorUtils<TENSOR_TYPE>::copyIgnoringOverlaps(THCState* state,         \
                                               TENSOR_TYPE* dst,        \
                                               TENSOR_TYPE* src) {      \
  return TENSOR_TYPE##_copyIgnoringOverlaps(state, dst, src);           \
}                                                                       \
                                                                        \
/* Returns false if there is no possibility that the tensor    */       \
/* has "overlapping" indices and true otherwise.               */       \
/* "Overlapping" indices are two+ valid indices that specify   */       \
/* the same offset within the tensor.                          */       \
/* The function does this by checking for a sufficient but not */       \
/* necessary condition of no overlap. In particular, that      */       \
/* that there exists an ordering of the tensor's dimensions    */       \
/* that is nicely "nested," with each dimension contained      */       \
/* within the next one.                                        */       \
bool                                                                    \
TensorUtils<TENSOR_TYPE>::maybeOverlappingIndices(THCState* state,      \
                                             TENSOR_TYPE* t) {          \
  /* Extract size/stride arrays; only consider size >1 dims. */         \
  SizeAndStride info[MAX_CUTORCH_DIMS];                                 \
                                                                        \
  int dims = THCTensor_nDimension(state, t);               \
  int nonSize1Dims = 0;                                                 \
  for (int i = 0; i < dims; ++i) {                                      \
    int64_t size = TensorUtils<TENSOR_TYPE>::getSize(state, t, i);      \
                                                                        \
    if (size > 1) {                                                     \
      info[nonSize1Dims].size = size;                                   \
      info[nonSize1Dims].stride =                                       \
        TensorUtils<TENSOR_TYPE>::getStride(state, t, i);               \
                                                                        \
      if (info[nonSize1Dims].stride < 1) {                              \
        return true;                                                    \
      }                                                                 \
                                                                        \
      ++nonSize1Dims;                                                   \
    }                                                                   \
  }                                                                     \
                                                                        \
  /* Short-circuits if tensor is a single element.             */       \
  if (nonSize1Dims == 0) {                                              \
    return false;                                                       \
  }                                                                     \
                                                                        \
  /* Ascending order (innermost dimension in sorted view is at [0]) */  \
  qsort(info, nonSize1Dims, sizeof(SizeAndStride), compareSizeAndStride); \
                                                                        \
  for (int i = 0; i < (nonSize1Dims - 1); ++i) {                        \
    if (((info[i].size - 1) * info[i].stride) >= info[i + 1].stride) {  \
      return true;                                                      \
    }                                                                   \
  }                                                                     \
                                                                        \
  return false;                                                         \
}                                                                       \
                                                                        \
bool                                                                    \
TensorUtils<TENSOR_TYPE>::canUse32BitIndexMath(THCState* state,         \
                                               TENSOR_TYPE* t,          \
                                               ptrdiff_t max_elem) {    \
  ptrdiff_t elements = TensorUtils<TENSOR_TYPE>::getNumElements(state, t);   \
  if (elements >= max_elem) {                                           \
    return false;                                                       \
  }                                                                     \
                                                                        \
  ptrdiff_t offset = 0;                                                 \
  ptrdiff_t linearId = elements - 1;                                    \
                                                                        \
  for (int i = THCTensor_nDimension(state, t) - 1; i >= 0; --i) { \
    ptrdiff_t curDimIndex =                                             \
      linearId % TensorUtils<TENSOR_TYPE>::getSize(state, t, i);        \
    ptrdiff_t curDimOffset = curDimIndex *                              \
      TensorUtils<TENSOR_TYPE>::getStride(state, t, i);                 \
    offset += curDimOffset;                                             \
    linearId /= TensorUtils<TENSOR_TYPE>::getSize(state, t, i);         \
  }                                                                     \
                                                                        \
  if (offset >= max_elem) {                                             \
    return false;                                                       \
  }                                                                     \
                                                                        \
  return true;                                                          \
}                                                                       \
                                                                        \
bool                                                                    \
TensorUtils<TENSOR_TYPE>::all32BitIndexable(THCState* state,            \
                                            TENSOR_TYPE** inputs,       \
                                            int numInputs) {            \
  for (int i = 0; i < numInputs; ++i) {                                 \
    if (!TensorUtils<TENSOR_TYPE>::canUse32BitIndexMath(state, inputs[i])) { \
      return false;                                                     \
    }                                                                   \
  }                                                                     \
  return true;                                                          \
}

IMPL_TENSOR_UTILS(THCudaByteTensor, uint8_t)
IMPL_TENSOR_UTILS(THCudaCharTensor, int8_t)
IMPL_TENSOR_UTILS(THCudaShortTensor, int16_t)
IMPL_TENSOR_UTILS(THCudaIntTensor, int32_t)
IMPL_TENSOR_UTILS(THCudaLongTensor, int64_t)
IMPL_TENSOR_UTILS(THCudaTensor, float)
IMPL_TENSOR_UTILS(THCudaDoubleTensor, double)

#ifdef CUDA_HALF_TENSOR
IMPL_TENSOR_UTILS(THCudaHalfTensor, half);
#endif

#undef IMPL_TENSOR_UTILS
