import torch
import torch.nn as nn
from torch.utils.data import DataLoader, ConcatDataset
from torch.autograd import Variable
import torch.optim as optim
import torch.backends.cudnn as cudnn

import numpy as np
import pickle
from models import deeplab_resnet 

import cv2
from PIL import Image
import scipy.misc

from datasets import DAVIS2016, YTB_VOS, MSRA10K, ECSSD


import sys
import os
import matplotlib.pyplot as plt
from tqdm import *
import random
from docopt import docopt
import timeit
from loss import cross_entropy_loss_weighted, cross_entropy_loss

from test_ms4chan import test

                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        
davis_path = '/home/hakjine/datasets/DAVIS/DAVIS-2016/DAVIS'
davis_im_path = os.path.join(davis_path, 'JPEGImages/480p')
davis_gt_path = os.path.join(davis_path, 'Annotations/480p')
vos_path = '/home/hakjine/datasets/Youtube-VOS/train/'
vos_im_path  = os.path.join(vos_path, 'JPEGImages')
vos_gt_path  = os.path.join(vos_path, 'Annotations')

start = timeit.timeit()
docstr = """Train ResNet-DeepLab on VOC12 (scefrom custom_transforms import aug_batchs) in pytorch using MSCOCO pretrained initialization 

Usage: 
    train.py [options]

Options:
    --NoLabels=<int>            The number of from custom_transforms import aug_batchfferent labels in training data, VOC has 21 labels, including background [default: 2]
    --lr=<float>                Learning Rate from custom_transforms import aug_batch [default: 0.001]
    -b, --batchSize=<int>       Num sample per batch [default: 14]
    --wtDecay=<float>           Weight decay during training [default: 0.0005]
    --gpu0=<int>                GPU number [default: 0]
    --maxIter=<int>             Maximum number of iterations [default: 25000]
"""

#    -b, --batchSize=<int>       num sample per batch [default: 1] currently only batch size of 1 is implemented, arbitrary batch size to be implemented soon
args = docopt(docstr, version='v0.1')
print(args)

cudnn.enabled = False
gpu0 = int(args['--gpu0'])


def outS(i):
    """Given shape of input image as i,i,3 in deeplab-resnet model, this function
    returns j such that the shape of output blob of is j,j,21 (21 in case of VOC)"""
    j = int(i)
    j = (j+1)/2
    #j = int(np.ceil((j+1)/2.0))
    #j = (j+1)/2
    return j

def resize_label_batch(label, size):
    label_resized = np.zeros((size,size,1,label.shape[3]))
    interp = nn.UpsamplingBilinear2d(size=(size, size))
    #interp = nn.UpsamplingNearest2d(size=(size, size))
    labelVar = Variable(torch.from_numpy(label.transpose(3, 2, 0, 1)))
    label_resized[:, :, :, :] = interp(labelVar).data.numpy().transpose(2, 3, 1, 0)
    label_resized[label_resized>0.3]  = 1
    label_resized[label_resized != 0]  = 1

    return label_resized


def lr_poly(base_lr, iter,max_iter,power):
    return base_lr*((1-float(iter)/max_iter)**(power))


def get_1x_lr_params_NOscale(model):
    """
    This generator returns all the parameters of the net except for 
    the last classification layer. Note that for each batchnorm layer, 
    requires_grad is set to False in deeplab_resnet.py, therefore this function does not return 
    any batchnorm parameter
    """
    b = []

    b.append(model.Scale.conv1)
    b.append(model.Scale.bn1)
    b.append(model.Scale.layer1)
    b.append(model.Scale.layer2)
    b.append(model.Scale.layer3)
    b.append(model.Scale.layer4)

    
    for i in range(len(b)):
        for j in b[i].modules():
            jj = 0
            for k in j.parameters():
                jj+=1
                if k.requires_grad:
                    yield k

def get_10x_lr_params(model):
    """
    This generator returns all the parameters for the last layer of the net,
    which does the classification of pixel into classes
    """

    b = []
    b.append(model.Scale.layer5.parameters())

    for j in range(len(b)):
        for i in b[j]:
            yield i

if not os.path.exists('data/snapshots'):
    os.makedirs('data/snapshots')


#model = deeplab_resnet.Res_Deeplab(2)
model = deeplab_resnet.Deep_EncoderDecoder(2)

"""
#saved_state_dict = torch.load('data/MS_DeepLab_resnet_pretrained_COCO_init.pth')
#saved_state_dict = torch.load('data/MS_DeepLab_resnet_trained_VOC.pth')
for i in saved_state_dict:
    #Scale.layer5.conv2d_list.3.weight
    i_parts = i.split('.')
    #if i_parts[1]=='layer5':
    #    saved_state_dict[i] = model.state_dict()[i]
    if i_parts[1] == 'conv1':
        saved_state_dict[i] = torch.cat((saved_state_dict[i], torch.FloatTensor(64, 1, 7, 7).normal_(0,0.0001)), 1)

model_dict = model.state_dict()
saved_state_dict = {k: v for k, v in saved_state_dict.items() if k in model_dict}
model_dict.update(saved_state_dict)

model.load_state_dict(model_dict)
"""


max_iter = int(args['--maxIter']) 
batch_size = int(args['--batchSize'])
weight_decay = float(args['--wtDecay'])
base_lr = float(args['--lr'])

model.float()
model.train()
#model.eval() # use_global_stats = True


db_davis_train = DAVIS2016(train=True,root=davis_path, aug=True)
#db_ytb_train = YTB_VOS(train=True, root='/home/hakjine/datasets/Youtube-VOS', aug=True)
db_ECSSD= ECSSD(root='/home/hakjine/datasets/ECSSD', aug=True)
db_MSRA10K= MSRA10K(root='/home/hakjine/datasets/MSRA10K', aug=True)
#db_train = ConcatDataset([db_davis_train, db_ytb_train])
#db_train = ConcatDataset([db_davis_train, db_ytb_train, db_ECSSD, db_MSRA10K])
db_train = ConcatDataset([db_davis_train, db_ECSSD, db_MSRA10K])

train_loader = DataLoader(db_train, batch_size=batch_size, shuffle=True)

model.cuda(gpu0)
#optimizer = optim.SGD([{'params': get_1x_lr_params_NOscale(model), 'lr': base_lr }, {'params': get_10x_lr_params(model), 'lr': 10*base_lr} ], lr = base_lr, momentum = 0.9,weight_decay = weight_decay)
optimizer = optim.SGD(filter(lambda p: p.requires_grad, model.parameters()), lr = base_lr, momentum = 0.9, weight_decay = weight_decay)

optimizer.zero_grad()

def vis(img, gt, out):

    plt.ion()
    plt.subplot(2, 2, 1)
    im = img.data.cpu().numpy()[:3, :, :].transpose(1, 2, 0)
    im[:,:,2] += 104.000699
    im[:,:,1] += 116.66877
    im[:,:,0] += 122.67892
    out = out.data.cpu().numpy()
    out = np.argmax(out, 0)
    #plt.imshow(cv2.cvtColor(im.astype('uint8'), cv2.COLOR_BGR2RGB))
    #im *= 255
    plt.imshow(im.astype('uint8'))
    plt.subplot(2, 2, 2)
    fg = img.data.cpu().numpy()[3:, :, :].transpose(1, 2, 0)
    plt.imshow(fg.squeeze())
    plt.subplot(2, 2, 3)
    plt.imshow(gt.squeeze())
    plt.subplot(2, 2, 4)
    plt.imshow(out)
    plt.show()
    plt.pause(0.05)
    plt.clf()

losses = []
acc = []
numerics = {'loss':losses, 'acc': acc}
import json
iter = 0
for epoch in range(0, 20):
    for ii, sample in enumerate(train_loader):
        iter += 1
        images, label = sample[0], sample[1]
        images = images.cuda(gpu0)


        out = model(images)
        loss = cross_entropy_loss_weighted(out, label.cuda())
        numerics['loss'].append(float(loss.data.cpu().numpy()))
        loss.backward()

        if iter %1 == 0:
            print 'iter = ',iter, 'of',max_iter,'completed, loss = ', (loss.data.cpu().numpy())

    
        if iter % 100 == 0:
            vis(images[0], label[0], out[0])

        optimizer.step()
        lr_ = lr_poly(base_lr,iter,max_iter,0.9)
        print '(poly lr policy) learning rate',lr_
        #optimizer = optim.SGD([{'params': get_1x_lr_params_NOscale(model), 'lr': lr_ }, {'params': get_10x_lr_params(model), 'lr': 10*lr_} ], lr = lr_, momentum = 0.9,weight_decay = weight_decay)
        optimizer = optim.SGD(filter(lambda p: p.requires_grad, model.parameters()), lr = lr_, momentum = 0.9, weight_decay = weight_decay)
        optimizer.zero_grad()

        if iter % 1000 == 0 and iter!=0:
            print 'taking snapshot ...'
            iou = test(model, save=True)
            numerics['acc'].append(iou)
            torch.save(model.state_dict(),'data/snapshots/masktrack-ED_sal'+str(iter)+'.pth')
            with open('./losses/masktrack-ED_sal'+str(iter)+'.json', 'w') as f:
                json.dump(numerics, f)

end = timeit.timeit()
print 'time taken ', end-start