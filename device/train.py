import os
import tqdm
import shutil
from ultralytics import YOLO


dataset_path = os.path.expanduser('~/Downloads/colorful_fashion_dataset_for_object_detection')



train = []
with open(os.path.join(dataset_path, 'ImageSets/Main/trainval.txt'), 'r') as f:
    for line in f.readlines():
        if line[-1]=='\n':
            line = line[:-1]
        train.append(line)

test = []
with open(os.path.join(dataset_path, 'ImageSets/Main/test.txt'), 'r') as f:
    for line in f.readlines():
        if line[-1]=='\n':
            line = line[:-1]
        test.append(line)


print(len(train), len(test))

images_path = os.path.join(dataset_path, 'JPEGImages')
annotations_path  = os.path.join(dataset_path, 'Annotations_txt')

for path in [
    os.path.join(dataset_path, 'train'),
    os.path.join(dataset_path, 'train', 'images'),
    os.path.join(dataset_path, 'train', 'labels'),
    os.path.join(dataset_path, 'test'),
    os.path.join(dataset_path, 'test', 'images'),
    os.path.join(dataset_path, 'test', 'labels'),
]:
    os.makedirs(path, exist_ok=True)


train_path = os.path.join(dataset_path, 'train')
test_path = os.path.join(dataset_path, 'test')

print('Copying Train Data..!!')
for i in tqdm.tqdm(train):
    a = shutil.copyfile(os.path.join(images_path, i+'.jpg'), os.path.join(train_path, 'images', i+'.jpg'))
    a = shutil.copyfile(os.path.join(annotations_path, i+'.txt'), os.path.join(train_path, 'labels', i+'.txt'))

print('Copying Test Data..!!')
for i in tqdm.tqdm(test):
    a = shutil.copyfile(os.path.join(images_path, i+'.jpg'), os.path.join(test_path, 'images', i+'.jpg'))
    a = shutil.copyfile(os.path.join(annotations_path, i+'.txt'), os.path.join(test_path, 'labels', i+'.txt'))



# Load a pre-trained YOLOv8 model (nano version)
model = YOLO('yolov8n.pt')

text = f"""
train: {dataset_path}/train
val: {dataset_path}/test

# number of classes
nc: 10

# class names
names: ['sunglass','hat','jacket','shirt','pants','shorts','skirt','dress','bag','shoe']
"""
with open("data.yaml", 'w') as file:
    file.write(text)

# Train the model
model.train(
    data='data.yaml',  # dataset configuration file
    epochs=5,                    # number of epochs
    imgsz=640                     # image size
)

model.save('tshirt_detection_model.pt')