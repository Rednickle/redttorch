#include "THCGeneral.h"
#include "THCTensor.hpp"
#include "THCTensorCopy.h"

#include <new>

#include "generic/THCTensor.cpp"
#include "THCGenerateAllTypes.h"

int THCTensor_nDimension(THCState *state, const _THCTensor *self) {
  return self->nDimension;
}

int64_t THCTensor_size(THCState *state, const _THCTensor *self, int dim) {
  THArgCheck((dim >= 0) && (dim < self->nDimension), 2, "out of range");
  return self->size[dim];
}

int64_t THCTensor_stride(THCState *state, const _THCTensor *self, int dim) {
  THArgCheck((dim >= 0) && (dim < self->nDimension), 2, "out of range");
  return self->stride[dim];
}
THLongStorage *THCTensor_newSizeOf(THCState *state, _THCTensor *self) {
  THLongStorage *size = THLongStorage_newWithSize(self->nDimension);
  THLongStorage_rawCopy(size, self->size);
  return size;
}

void THCTensor_resize(THCState *state, _THCTensor *self, THLongStorage *size, THLongStorage *stride) {
  THArgCheck(size != NULL, 2, "invalid size");
  if(stride)
    THArgCheck(stride->size == size->size, 3, "invalid stride");

  THCTensor_resizeNd(state, self, size->size, THLongStorage_data(size), (stride ? THLongStorage_data(stride) : NULL));
}

void THCTensor_resizeAs(THCState *state, _THCTensor *self, _THCTensor *src) {
  int isSame = 0;
  int d;
  if(self->nDimension == src->nDimension)
  {
    isSame = 1;
    for(d = 0; d < self->nDimension; d++)
    {
      if(self->size[d] != src->size[d])
      {
        isSame = 0;
        break;
      }
    }
  }

  if(!isSame)
    THCTensor_resizeNd(state, self, src->nDimension, src->size, NULL);
}

void THCTensor_resizeNd(THCState *state, _THCTensor *self, int nDimension, int64_t *size, int64_t *stride)
{
  int d;
  int nDimension_;
  ptrdiff_t totalSize;
  int hascorrectsize = 1;

  nDimension_ = 0;
  for(d = 0; d < nDimension; d++)
  {
    if(size[d] > 0)
    {
      nDimension_++;
      if((self->nDimension > d) && (size[d] != self->size[d]))
        hascorrectsize = 0;

      if((self->nDimension > d) && stride && (stride[d] >= 0) && (stride[d] != self->stride[d]))
        hascorrectsize = 0;
    }
    else
      break;
  }
  nDimension = nDimension_;

  if(nDimension != self->nDimension)
    hascorrectsize = 0;

  if(hascorrectsize)
    return;

  if(nDimension > 0)
  {
    if(nDimension != self->nDimension)
    {
      self->size = (int64_t*)THRealloc(self->size, sizeof(int64_t)*nDimension);
      self->stride = (int64_t*)THRealloc(self->stride, sizeof(int64_t)*nDimension);
      self->nDimension = nDimension;
    }

    totalSize = 1;
    for(d = self->nDimension-1; d >= 0; d--)
    {
      self->size[d] = size[d];
      if(stride && (stride[d] >= 0) )
        self->stride[d] = stride[d];
      else
      {
        if(d == self->nDimension-1)
          self->stride[d] = 1;
        else
          self->stride[d] = self->size[d+1]*self->stride[d+1];
      }
      totalSize += (self->size[d]-1)*self->stride[d];
    }

    if(totalSize+self->storageOffset > 0)
    {
      if(!self->storage)
        self->storage = THCStorage_new(state, self->storage->scalar_type);
      if(totalSize+self->storageOffset > self->storage->size)
        THCStorage_resize(state, self->storage, totalSize+self->storageOffset);
    }
  }
  else
    self->nDimension = 0;
}

void THCTensor_set(THCState *state, _THCTensor *self, _THCTensor *src)
{
  if(self != src)
    THCTensor_setStorageNd(state,
                           self,
                           src->storage,
                           src->storageOffset,
                           src->nDimension,
                           src->size,
                           src->stride);
}

void THCTensor_setStorageNd(THCState *state, _THCTensor *self, THCStorage *storage, ptrdiff_t storageOffset, int nDimension, int64_t *size, int64_t *stride)
{
  /* storage */
  if(self->storage != storage)
  {
    if(self->storage)
      THCStorage_free(state, self->storage);

    if(storage)
    {
      self->storage = storage;
      THCStorage_retain(state, self->storage);
    }
    else
      self->storage = THCStorage_new(state, self->storage->scalar_type);
  }

  /* storageOffset */
  if(storageOffset < 0)
    THError("Tensor: invalid storage offset");
  self->storageOffset = storageOffset;

  /* size and stride */
  THCTensor_resizeNd(state, self, nDimension, size, stride);
}


void THCTensor_squeeze1d(THCState *state, _THCTensor *self, _THCTensor *src, int dimension)
{
  int d;

  if(!src)
    src = self;

  THArgCheck(dimension < src->nDimension, 3, "dimension out of range");

  THCTensor_set(state, self, src);

  if(src->size[dimension] == 1 && src->nDimension > 1)
  {
    for(d = dimension; d < self->nDimension-1; d++)
    {
      self->size[d] = self->size[d+1];
      self->stride[d] = self->stride[d+1];
    }
    self->nDimension--;
  }
}

void THCTensor_unsqueeze1d(THCState *state, _THCTensor *self, _THCTensor *src, int dimension)
{
  int d;

  if(!src)
    src = self;

  THArgCheck((dimension >= 0) && (dimension <= src->nDimension), 3, "dimension out of range");
  THArgCheck(src->nDimension > 0, 3, "cannot unsqueeze empty tensor");

  THCTensor_set(state, self, src);

  self->size = (int64_t*)THRealloc(self->size, sizeof(int64_t)*(self->nDimension+1));
  self->stride = (int64_t*)THRealloc(self->stride, sizeof(int64_t)*(self->nDimension+1));
  self->nDimension++;
  for (d = self->nDimension-1; d > dimension; d--) {
    self->size[d] = self->size[d-1];
    self->stride[d] = self->stride[d-1];
  }
  if (dimension+1 < self->nDimension) {
    self->stride[dimension] = self->size[dimension+1] * self->stride[dimension+1];
  } else {
    self->stride[dimension] = 1;
  }
  self->size[dimension] = 1;
}

bool THCTensor_isContiguous(THCState *state, const _THCTensor *self) {
  int64_t z = 1;
  int d;
  for(d = self->nDimension-1; d >= 0; d--)
  {
    if(self->size[d] != 1)
    {
      if(self->stride[d] == z)
        z *= self->size[d];
      else
        return false;
    }
  }
  return true;
}

bool THCTensor_allContiguous(THCState *state, const _THCTensor **inputs, int numInputs) {
  THAssert(numInputs > 0);
  for (int i = 0; i < numInputs; ++i) {
    if (!THCTensor_isContiguous(state, inputs[i])) {
      return false;
    }
  }
  return true;
}

ptrdiff_t THCTensor_nElement(THCState *state, const _THCTensor *self) {
  if(self->nDimension == 0)
    return 0;
  else
  {
    ptrdiff_t nElement = 1;
    int d;
    for(d = 0; d < self->nDimension; d++)
      nElement *= self->size[d];
    return nElement;
  }
}

void THCTensor_retain(THCState *state, _THCTensor *self) {
  if(self->flag & TH_TENSOR_REFCOUNTED)
    self->refcount++;
}


void THCTensor_free(THCState *state, _THCTensor *self) {
  if(!self)
    return;

  if(self->flag & TH_TENSOR_REFCOUNTED)
  {
    if(--self->refcount == 0)
    {
      THFree(self->size);
      THFree(self->stride);
      if(self->storage)
        THCStorage_free(state, self->storage);
      self->refcount.~atomic<int>();
      THFree(self);
    }
  }
}

int THCTensor_getDevice(THCState* state, const _THCTensor* tensor) {
  if (!tensor->storage) return -1;
  return THCStorage_getDevice(state, tensor->storage);
}

bool THCTensor_allSameDevice(THCState* state, const _THCTensor ** inputs, int numInputs) {
  THAssert(numInputs > 0);
  int device = THCTensor_getDevice(state, inputs[0]);
  for (int i = 1; i < numInputs; ++i) {
    if (THCTensor_getDevice(state, inputs[i]) != device) {
      return false;
    }
  }
  return true;
}

int64_t THCTensor_size(THCState *state, const THCTensor *self, int dim)
{
  THArgCheck((dim >= 0) && (dim < self->nDimension), 2, "out of range");
  return self->size[dim];
}

int64_t THCTensor_stride(THCState *state, const THCTensor *self, int dim)
{
  THArgCheck((dim >= 0) && (dim < self->nDimension), 2, "out of range");
  return self->stride[dim];
}
