## This file includes all the operations in patching. It can efficiently process patching with as small computation cost as possible.
import torch
import numpy as np
import torchvision
from torchvision import datasets, models, transforms
from torch.utils.data.dataset import Dataset
from torch.utils.data.sampler import SequentialSampler
import scipy.io

# Patch class for function 'patching'. It can get an item at a time.
class Patch(Dataset):
    def __init__(self, lr_patches, hr_patches):
        self.lr_data = lr_patches
        self.hr_data = hr_patches
       
    def transform(self, image):
        '''
        This function transforms the input patch (64,64,64) 
        from int16(12): 0-4095 to float: 0.0-1.0
        
        '''
        image_float = image.float() / 4095.0
        image_float = torch.unsqueeze(image_float,0)
        return image_float
    def __getitem__(self, idx):
        image_lr = self.lr_data[idx,:,:,:]
        image_hr = self.hr_data[idx,:,:,:]
        sample_hr = self.transform(image_hr)
        sample_lr = self.transform(image_lr)
        
        return (sample_lr, sample_hr)
    def __len__(self):
        return self.lr_data.shape[0]
    

def patching(lr_data, hr_data, patch_size = 2, cube_size = 64, usage = 1.0, margin =3, is_training=True):
    '''
    This function makes patches from the input 3D image. It fulfills random patch selection for training period, and sliding window patch seperation for evaluation period. Note that dtype transform from int16(12): 0-4095 to float: 0.0-1.0 is applied on patches in order to save memory.

    (Input) l/hr_data: a torch.ShortTensor (B,z,x,y) with dtype=int16 (the exact dtype is int12, from 0-4095)
    (Input) patch_size: define the patch size. 2 in this project (Default).
    (Input) cube_size: define the 3D cube size. 64 in this project (Default).
    (Input) usage: The percentage of usage of one cluster of patches. For example: usage= 0.5 means to randomly pick 50% patches from a cluster of 200 patches.
    (Input) margin: The size that one patch has to be cut off. Only implemented in evaluation period. 3 in this project (Default).               
    (Input) is_training: True for training and validation set, False for evaluation and test set.
    (Output) patch_loader: a torch.DataLoader for picking patches from one batch.
    '''
    #import idx_mine to avoid unwanted patch indices
    mat = scipy.io.loadmat('ecbm6040/patching/idx_mine.mat')
    idx_mine = mat['idx_mine']
    idx_mine = idx_mine[0].tolist()
    # here we are not setting mines. We want all patches.
    idx_mine = []
    
    if is_training:
        stride = cube_size # patch stride
        lr_patches = lr_data.unfold(1, cube_size, stride).unfold(2, cube_size, stride).unfold(3, cube_size, stride)
        hr_patches = hr_data.unfold(1, cube_size, stride).unfold(2, cube_size, stride).unfold(3, cube_size, stride)
        lr_patches = lr_patches.contiguous().view(-1, cube_size, cube_size, cube_size)
        hr_patches = hr_patches.contiguous().view(-1, cube_size, cube_size, cube_size)
        patches = Patch(lr_patches, hr_patches)
        num_patches = len(patches)
        patch_split= usage # define the percentage of selecting patches in a batch
        patch_take = int(patch_split * num_patches) # the total patches selected in a batch 
        indices_undemined = list(range(num_patches))
        indices= list(set(indices_undemined) - set(idx_mine)) # exclude unwanted patch indices
        np.random.shuffle(indices)
        patch_indices = indices[:patch_take]
        patch_sampler = SequentialSampler(patch_indices)
        patch_loader = torch.utils.data.DataLoader(dataset=patches, 
                                        batch_size=patch_size, 
                                        sampler=patch_sampler,
                                        shuffle=False)
        return patch_loader
    else:
        stride = cube_size- 2 * margin # patch stride, when merging patches, we need to reduce stride for we need to give up the margin to avoid margin effect.
        padding=[20, 17, 17] # calculate how many paddings we need to care for edges of images, for simplicity, the numbers are pre-calculated by default patch size, for different size of input, it should be different.
        # Padding
        lr_data_padded = torch.zeros([lr_data.shape[0] ,lr_data.shape[1] + 2 * padding[0],lr_data.shape[2]+ 2 * padding[1],lr_data.shape[3] + 2 * padding[2]])
        hr_data_padded = torch.zeros([lr_data.shape[0] ,hr_data.shape[1] + 2 * padding[0],hr_data.shape[2]+ 2 * padding[1],hr_data.shape[3] + 2 * padding[2]])
        lr_data_padded[:, padding[0]: lr_data.shape[1]+padding[0], padding[1]: lr_data.shape[2]+padding[1], 
                       padding[2]: lr_data.shape[3]+padding[2]] = lr_data
        hr_data_padded[:, padding[0]: hr_data.shape[1]+padding[0], padding[1]: hr_data.shape[2]+padding[1], 
                       padding[2]: hr_data.shape[3]+padding[2]] = hr_data
        lr_patches = lr_data_padded.unfold(1, cube_size, stride).unfold(2, cube_size, stride).unfold(3, cube_size, stride)
        hr_patches = hr_data_padded.unfold(1, cube_size, stride).unfold(2, cube_size, stride).unfold(3, cube_size, stride)
        lr_patches = lr_patches.contiguous().view(-1, cube_size, cube_size, cube_size)
        hr_patches = hr_patches.contiguous().view(-1, cube_size, cube_size, cube_size)
        patches = Patch(lr_patches, hr_patches)
        patch_loader = torch.utils.data.DataLoader(dataset=patches, 
                                        batch_size=patch_size, 
                                        sampler=None,
                                        shuffle=False)
        return patch_loader

def depatching(patches, batch_size, margin = 3, image_size = [192,320,320]):
    '''
    This function merges patches to the original 3D image. Note that this function based on tensor, but detached. 
    
    (Input) patches: The group of patches in Tensor to be depatched. The size should be (num_patches, channel, cube_size, cube_size, cube_size)
    (Input) batch_size: The batch size which determines the number of subjects with whole 3D image.
    (Input) margin: The size that one patch has to be cut off. 3 in this project (Default).
    (Input) image_size: The size of original 3D image size [z,x,y]. [256,320,320] in this project (Default).
    (Output) image: # batch_size of the original 3D images in numpy.   
    '''
    image_size = [192,320,320]
    padding=[20, 17, 17] # calculate how many paddings we need to care for edges of images, for simplicity, the numbers are pre-calculated by default patch size, for different size of input, it should be different.
    cube_size = patches.shape[-1]
    tmp = patches.view(batch_size, -1, cube_size, cube_size, cube_size)
    real_tmp = tmp[:,:,margin:-margin,margin:-margin,margin:-margin]
    cube_size_cropped = real_tmp.shape[-1]
    merged_image_size=[image_size[0]+2*(padding[0]-margin),image_size[1]+2*(padding[1]-margin),
                       image_size[2]+2*(padding[2]-margin)]
    merged_image = torch.zeros(batch_size, merged_image_size[0], merged_image_size[1], merged_image_size[2])
    nz = int(merged_image_size[0] / cube_size_cropped)
    nx = int(merged_image_size[1] / cube_size_cropped)
    ny = int(merged_image_size[2] / cube_size_cropped)
    real_tmp = real_tmp.view(batch_size, nz, -1, cube_size_cropped, cube_size_cropped, cube_size_cropped)
    print('################### real tmp 6D ####################')
    print(real_tmp.size())

    real_tmp = real_tmp.view(batch_size, nz, nx, -1, cube_size_cropped, cube_size_cropped, cube_size_cropped)
    print('################### real tmp 7D ####################')
    print(real_tmp.size())
    image = torch.zeros(batch_size, image_size[0], image_size[1], image_size[2])
    print('################# cube_size_cropped ###############')
    #print(cube_size_cropped.size())

    for i in range(nz):
        for j in range(nx):
            for k in range(ny):
                
                merged_image[:,cube_size_cropped*i:cube_size_cropped*(i+1), cube_size_cropped*j:cube_size_cropped*(j+1), 
                             cube_size_cropped*k:cube_size_cropped*(k+1)] = real_tmp[:,i,j,k,:,:,:] 
    print('3333333 merged_image 3333333')
    #print(merged_image.size())
    image=merged_image[:,(padding[0]-margin):-(padding[0]-margin),(padding[1]-margin):-(padding[1]-margin),
                       (padding[2]-margin):-(padding[2]-margin)]
    #print(image.size())
    return image
