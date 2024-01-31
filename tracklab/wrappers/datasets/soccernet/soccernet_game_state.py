import os
import pandas as pd
import json
from pathlib import Path
from tracklab.datastruct import TrackingDataset, TrackingSet
from tracklab.utils import xywh_to_ltwh


class SoccerNetGameState(TrackingDataset):
    def __init__(self, dataset_path: str, *args, **kwargs):
        self.dataset_path = Path(dataset_path)
        assert self.dataset_path.exists(), f"'{self.dataset_path}' directory does not exist. Please check the path or download the dataset following the instructions here: https://github.com/SoccerNet/sn-game-state"

        train_set = load_set(self.dataset_path / "train")
        val_set = load_set(self.dataset_path / "validation")
        # test_set = load_set(self.dataset_path / "challenge")
        test_set = None

        super().__init__(dataset_path, train_set, val_set, test_set, *args, **kwargs)

def extract_category(attributes):
    if attributes['role'] == 'goalkeeper':
        team = attributes['team']
        role = "goalkeeper"
        jersey_number = None
        if attributes['jersey'] is not None:
            jersey_number = int(attributes['jersey']) if attributes['jersey'].isdigit() else None
        category = f"{role}_{team}_{jersey_number}" if jersey_number is not None else f"{role}_{team}"
    elif attributes['role'] == "player":
        team = attributes['team']
        role = "player"
        jersey_number = None
        if attributes['jersey'] is not None:
            jersey_number = int(attributes['jersey']) if attributes['jersey'].isdigit() is not None else None
        category = f"{role}_{team}_{jersey_number}" if jersey_number is not None else f"{role}_{team}"
    elif attributes['role'] == "referee":
        team = None
        role = "referee"
        jersey_number = None
        # position = additional_info  # TODO no position for referee in json file (referee's position is not specified in the dataset)
        category = f"{role}"
    elif attributes['role'] == "ball":
        team = None
        role = "ball"
        jersey_number = None
        category = f"{role}"
    else:
        assert attributes['role'] == "other"
        team = None
        role = "other"
        jersey_number = None
        category = f"{role}"
    return category
    
    
def dict_to_df_detections(annotation_dict, categories_list):
    df = pd.DataFrame.from_dict(annotation_dict)
    df['image_id'] = df['image_id']

    annotations_pitch_camera = df.loc[df['supercategory'] != 'object']   # remove the rows with non-human categories
    
    df = df.loc[df['supercategory'] == 'object']        # remove the rows with non-human categories
    
    df['bbox_ltwh'] = df.apply(lambda row: xywh_to_ltwh([row['bbox_image']['x_center'], row['bbox_image']['y_center'], row['bbox_image']['w'], row['bbox_image']['h']]), axis=1)
    df['team'] = df.apply(lambda row: row['attributes']['team'], axis=1)
    df['role'] = df.apply(lambda row: row['attributes']['role'], axis=1)
    df['jersey_number'] = df.apply(lambda row: row['attributes']['jersey'], axis=1)
    df['position'] = None # df.apply(lambda row: row['attributes']['position'], axis=1)         for now there is no position in the json file
    df['category'] = df.apply(lambda row: extract_category(row['attributes']), axis=1)
    df['person_id'] = df['track_id']  # Create person_id column with the same content as track_id
    
    columns = ['id', 'image_id', 'track_id', 'person_id', 'bbox_ltwh', 'bbox_pitch', 'team', 'role', 'jersey_number', 'position', 'category']
    df = df[columns]
    
    video_level_categories = list(df['category'].unique())
    
    return df, annotations_pitch_camera, video_level_categories  

def read_json_file(file_path):
    with open(file_path, 'r') as file:
        file_json = json.load(file)
    return file_json


def load_set(dataset_path):
    video_metadatas_list = []
    image_metadata_list = []
    annotations_pitch_camera_list = []
    detections_list = []
    categories_list = []

    image_counter = 0
    for video_folder in sorted(os.listdir(dataset_path)):  # Sort videos by name
        video_folder_path = os.path.join(dataset_path, video_folder)
        if os.path.isdir(video_folder_path):
            # Read the gamestate.json file
            gamestate_path = os.path.join(video_folder_path, 'Labels-GameState.json')
            gamestate_data = read_json_file(gamestate_path)

            info_data = gamestate_data['info']
            images_data = gamestate_data['images']
            annotations_data = gamestate_data['annotations']
            categories_data = gamestate_data['categories']
            video_id = info_data.get("id", str(len(video_metadatas_list)+1))

            detections_df, annotation_pitch_camera_df, video_level_categories = dict_to_df_detections(annotations_data, categories_data)
            # detections_df['image_id'] = detections_df['image_id'] - 1 + image_counter
            detections_df['video_id'] = video_id
            detections_df['visibility'] = 1
            detections_list.append(detections_df)

            # Append video metadata
            nframes = int(info_data.get('seq_length', 0))
            video_metadata = {
                'id': video_id,
                'name': info_data.get('name', ''),
                'nframes': nframes,
                'frame_rate': int(info_data.get('frame_rate', 0)),
                'seq_length': nframes,
                'im_width': int(images_data[0].get('width', 0)),
                'im_height': int(images_data[0].get('height', 0)),
                'game_id': int(info_data.get('gameID', 0)),
                'action_position': int(info_data.get('actionPosition', 0)),
                'action_class': info_data.get('actionClass', ''),
                'visibility': info_data.get('visibility', ''),
                'clip_start': int(info_data.get('clipStart', 0)),
                'game_time_start': info_data.get('gameTimeStart', '').split(' - ')[1],
                # Remove the half period index
                'game_time_stop': info_data.get('gameTimeStop', '').split(' - ')[1],  # Remove the half period index 
                'clip_stop': int(info_data.get('clipStop', 0)),
                'num_tracklets': int(info_data.get('num_tracklets', 0)),
                'half_period_start': int(info_data.get('gameTimeStart', '').split(' - ')[0]),
                # Add the half period start column
                'half_period_stop': int(info_data.get('gameTimeStop', '').split(' - ')[0]),
                # Add the half period stop column
            }

            categories_list += video_level_categories

            # Append video metadata
            video_metadatas_list.append(video_metadata)



            # Append image metadata
            img_folder_path = os.path.join(video_folder_path, info_data.get('im_dir', 'img1'))
            img_metadata_df = pd.DataFrame({
                'frame': [i for i in range(0, nframes)],
                'id': [i['image_id'] for i in images_data],
                # 'id': [image_counter + i for i in range(0, nframes)],
                'video_id': video_id,
                'file_path': [os.path.join(img_folder_path, i['file_name']) for i in
                              images_data],
                'is_labeled': [i['is_labeled'] for i in images_data],
            })
            # extract the camera parameters
            # img_metadata_df = pd.DataFrame.merge(img_metadata_df, video_camera_df, left_on='id', right_on='image_id')
            # img_metadata_df = img_metadata_df.drop(columns=['image_id'])

            image_counter += nframes
            image_metadata_list.append(img_metadata_df)
            annotation_pitch_camera_df["video_id"] = video_id
            annotations_pitch_camera_list.append(annotation_pitch_camera_df)

    categories_list = [{'id': i + 1, 'name': category, 'supercategory': 'person'} for i, category in
                       enumerate(sorted(set(categories_list)))]

    # Assign the categories to the video metadata  # TODO at dataset level?
    for video_metadata in video_metadatas_list:
        video_metadata['categories'] = categories_list

    # Concatenate dataframes
    video_metadata = pd.DataFrame(video_metadatas_list)
    image_metadata = pd.concat(image_metadata_list, ignore_index=True)
    detections = pd.concat(detections_list, ignore_index=True)

    # add camera parameters and pitch as ground truth
    pitch_camera = pd.concat(annotations_pitch_camera_list, ignore_index=True)
    pitch_gt = (pitch_camera[["image_id", "video_id", "lines"]]
                [pitch_camera.supercategory=="pitch"].set_index("image_id", drop=True))
    camera_gt = (pitch_camera[["image_id", "parameters", "relative_mean_reproj", "accuracy@5"]]
                 [pitch_camera.supercategory=="camera"].set_index("image_id", drop=True))
    image_gt = pitch_gt.join(camera_gt)

    # Add category id to detections
    category_to_id = {category['name']: category['id'] for category in categories_list}
    detections['category_id'] = detections['category'].apply(lambda x: category_to_id[x])

    # Set 'id' column as the index in the detections and image dataframe
    detections['id'] = detections.index

    detections.set_index("id", drop=True, inplace=True)
    image_metadata.set_index("id", drop=True, inplace=True)
    video_metadata.set_index("id", drop=True, inplace=True)


    # Reorder columns in dataframes
    video_metadata_columns = ['name', 'nframes', 'frame_rate', 'seq_length', 'im_width', 'im_height', 'game_id', 'action_position',
                              'action_class', 'visibility', 'clip_start', 'game_time_start', 'clip_stop', 'game_time_stop',
                              'num_tracklets',
                              'half_period_start', 'half_period_stop', 'categories']
    video_metadata_columns.extend(set(video_metadata.columns) - set(video_metadata_columns))
    video_metadata = video_metadata[video_metadata_columns]
    image_metadata_columns = ['video_id', 'frame', 'file_path', 'is_labeled']
    image_metadata_columns.extend(set(image_metadata.columns) - set(image_metadata_columns))
    image_metadata = image_metadata[image_metadata_columns]
    detections_column_ordered = ['image_id', 'video_id', 'track_id', 'person_id', 'bbox_ltwh', 'visibility']
    detections_column_ordered.extend(set(detections.columns) - set(detections_column_ordered))
    detections = detections[detections_column_ordered]
    return TrackingSet(
        video_metadata,
        image_metadata,
        detections,
        image_gt,
    )