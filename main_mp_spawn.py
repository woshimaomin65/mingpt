import pdb
import os
import torch
import yaml
from argparse import Namespace
from utils.import_class import import_class
from torch.utils.data.dataloader import DataLoader
from utils.tools import batch_end_callback

import torch.multiprocessing as mp #ddp
from torch.utils.data import DistributedSampler #ddp
from torch.distributed import init_process_group, destroy_process_group #ddp
from torch.nn.parallel import DistributedDataParallel as DDP   #ddp
#ddp

def ddp_setup(rank, world_size=1, **kw):
    os.environ["MASTER_ADDR"] = "localhost"
    os.environ["MASTER_PORT"] = '12355'
    init_process_group(backend="nccl", rank=rank, world_size=world_size)
    
def cleanup():
    destroy_process_group()

def main_ddp(rank, world_size, config):
    #是否需要ddp
    config = Namespace(**config)
    config.ddp_setup["params"].update({"world_size": world_size, "rank": rank})
    ddp_setup(**config.ddp_setup["params"]) #ddp
    #初始化模型 tokenizer， model_class
    model = import_class(**config.model)(**config.model["params"])
    #加载模型
    if config.model["is_from_pretrained"]:
        model.from_pretrained(**config.model["params"])
    print(f"gpu_id: {rank}")    
    model.to(rank) #ddp
    model = DDP(model, device_ids=[rank])  #ddp
    #加载训练数据
    train_dataset = import_class(**config.train_dataset)(**config.train_dataset["params"])
    train_sampler=torch.utils.data.RandomSampler(train_dataset, replacement=True, num_samples=int(1e10))
    train_loader = DataLoader(train_dataset, **config.train_dataloader)
    #加载测试数据
    test_dataset = import_class(**config.test_dataset)(**config.test_dataset["params"])
    test_sampler=torch.utils.data.RandomSampler(test_dataset, replacement=True, num_samples=int(1e10))
    test_loader = DataLoader(test_dataset, **config.test_dataloader)
    #初始化训练框架
    trainer = import_class(**config.trainer)(model, train_loader, test_loader, is_ddp=True, **config.trainer["params"])
    if rank == 0:
        trainer.set_callback('on_batch_end', batch_end_callback)
    #训练
    try:
        trainer.run()
    except:
        cleanup()    
    cleanup()    

if __name__ == "__main__":
    #加载配置文件
    config = yaml.safe_load(open("conf/conf_mingpt.yml"))
    config = Namespace(**config)
    if config.ddp_setup["is_ddp"]:
        config=vars(config)
        world_size = torch.cuda.device_count()
        mp.spawn(main_ddp, args=(world_size, config,), nprocs=world_size, join=True)
    else:
        main(config)    
