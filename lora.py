import torch
import torch.utils
import torch.utils.data
import torch.nn.utils.parametrize as parametrize
import torchvision.datasets as datasets
import torchvision.transforms as transforms
import torch.nn as nn
from tqdm import tqdm


_ = torch.manual_seed(0)

transform = transforms.Compose([transforms.ToTensor(),
                                transforms.Normalize((0.1307,), (0.3081,))])

#  MNIST dataset for training
mnist_trainset = datasets.MNIST(root='./data', train=True, download=True, transform=transform)
train_loader = torch.utils.data.DataLoader(mnist_trainset, batch_size=10, shuffle=True)

#  MNIST dataset for test
mnist_testset = datasets.MNIST(root='./data', train=False, download=True, transform=transform)
test_loader = torch.utils.data.DataLoader(mnist_testset, batch_size=10, shuffle=True)

device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")


class RichBoyNet(nn.Module):

    def __init__(self, hidden_size_1=1000, hidden_size_2=2000):
        super(RichBoyNet, self).__init__()
        self.linear1 = nn.Linear(28*28, hidden_size_1, hidden_size_2)
        self.linear2 = nn.Linear(hidden_size_1, hidden_size_2)
        self.linear3 = nn.Linear(hidden_size_2, 10)
        self.relu = nn.ReLU()

    def forward(self, img):
        x = img.view(-1, 28*28)
        x = self.relu(self.linear1(x))
        x = self.relu(self.linear2(x))
        x = self.linear3(x)
        return x


net = RichBoyNet().to(device)


def train(train_loader, net, epochs=5, total_iterations_limit=None):
    cross_el = nn.CrossEntropyLoss()
    optimizer = torch.optim.Adam(net.parameters(), lr=0.001)

    total_iterations = 0

    for epoch in range(epochs):
        net.train()

        loss_sum = 0
        num_iterations = 0

        data_iterator = tqdm(train_loader, desc=f'Epoch{epoch+1}')
        if total_iterations_limit is not None:
            data_iterator.total = total_iterations_limit
        for data in data_iterator:
            num_iterations += 1
            total_iterations += 1
            x, y = data
            x = x.to(device)
            y = y.to(device)
            optimizer.zero_grad()
            output = net(x.view(-1, 28*28))
            loss = cross_el(output, y)
            loss_sum += loss.item()
            avg_loss = loss_sum / num_iterations
            data_iterator.set_postfix(loss=avg_loss)
            loss.backward()
            optimizer.step()

            if total_iterations_limit is not None and total_iterations >= total_iterations_limit:
                return


train(train_loader, net, epochs=1)


original_weights = {}
for name, param in net.named_parameters():
    original_weights[name] = param.clone().detach()


def test():
    correct = 0
    total = 0

    wrong_counts = [0 for i in range(10)]

    with torch.no_grad():
        for data in tqdm(test_loader, desc='Testing'):
            x, y = data
            x = x.to(device)
            y = y.to(device)
            output = net(x.view(-1, 784))
            for idx, i in enumerate(output):
                if torch.argmax(i) == y[idx]:
                    correct +=1
                else:
                    wrong_counts[y[idx]] +=1
                total +=1
    print(f'Accuracy:{round(correct/total, 3)}')
    for i in range(len(wrong_counts)):
        print(f'wrong counts for the digit {1}: {wrong_counts[i]}')


class LoRAParametrization(nn.Module):

    def __init__(self, features_in, features_out, rank = 1, alpha = 1, device = 'cpu'):
        super().__init__()
        self.lora_A = nn.Parameter(torch.zeros(rank, features_out).to(device))
        self.lora_B = nn.Parameter(torch.zeros(features_in,rank).to(device))
        nn.init.normal_(self.lora_A, mean = 0, std = 1)
        self.scale = alpha / rank
        self.enabled = True

    def forward(self, original_weights):
        if self.enabled:
            return original_weights + torch.matmul(self.lora_B, 
                                                   self.lora_A).view(original_weights.shape) * self.scale
        else:
            return original_weights


def linear_layer_parametrization(layer, device, rank=1, lora_alpha=1):
    features_in, features_out = layer.weight.shape
    return LoRAParametrization(features_in, features_out, rank = rank,
                               alpha = lora_alpha, device = device)


parametrize.register_parametrization(
    net.linear1, "weight", linear_layer_parametrization(net.linear1, device)
)


parametrize.register_parametrization(
    net.linear2, "weight", linear_layer_parametrization(net.linear2, device)
)


parametrize.register_parametrization(
    net.linear3, "weight", linear_layer_parametrization(net.linear3, device)
)


def enable_disable_lora(enabled=True):
    for layer in [net.linear1, net.linear2, net.linear3]:
        layer.parametrizations["weight"][0].enabled = enabled


total_parameters_lora = 0
total_parameters_non_lora = 0
for index, layer in enumerate([net.linear1, net.linear2, net.linear3]):
    total_parameters_lora += layer.parameterizations["weight"][0].lora_A.nelement()+layer.parameterizations["weight"][0].lora_B.nelement()
    total_parameters_non_lora += layer.weight.nelement() + layer.bias.nelement()
    print(f'Layer{index+1}: W: {layer.weight.shape} + B: {layer.bias.shape} + Lora_A: {layer.parameterizations["weight"][0].lora_A.shape} + Lora_B: {layer.parametrizations["weight"][0].lora_B.shape}')


print(f'Total number of parameters (original): {total_parameters_non_lora:,}')
print(f'Total number of parameters (original + LoRA): {total_parameters_lora + total_parameters_non_lora:,}')
print(f'Parameters introduced by LoRA: {total_parameters_lora:,}')
parameters_incremment = (total_parameters_lora / total_parameters_non_lora) * 100
print(f'Parameters incremment: {parameters_incremment:.3f}%')

for name, param in net.named_parameters():
    if 'lora' not in name:
        print(f'Freezing non-LoRA parameter {name}')
        param.requires_grad = False


mnist_trainset = datasets.MNIST(root='./data', train=True, download=True, transform=transform)
exclude_indices = mnist_trainset.targets == 9
mnist_trainset.data = mnist_trainset.data[exclude_indices]
mnist_trainset.targets = mnist_trainset.targets[exclude_indices]

train_loader = torch.utils.data.DataLoader(mnist_trainset, batch_size=10, shuffle=True)

train(train_loader, net, epochs=1, total_iterations_limit=100)
