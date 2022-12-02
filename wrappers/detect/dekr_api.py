import sys
import cv2
import numpy as np
import torch
import torchvision.transforms as T

from pbtrack.datastruct.detections import Detection
from pbtrack.core.detector import Detector
from pbtrack.utils.coordinates import kp_to_bbox, rescale_keypoints

from hydra.utils import to_absolute_path
sys.path.append(to_absolute_path("plugins/detect/DEKR/lib"))

import models
from core.inference import get_multi_stage_outputs
from core.inference import aggregate_results
from core.nms import pose_nms
from core.match import match_pose_to_heatmap
from utils.transforms import resize_align_multi_scale
from utils.transforms import get_final_preds
from utils.transforms import get_multi_scale_size
from utils.rescore import rescore_valid

# TODO fixmes and add the training part
class DEKR(Detector):
    def __init__(self, cfg, device):
        self.cfg = cfg
        self.device = device
        
        self.model = eval("models." + cfg.MODEL.NAME + ".get_pose_net")( # FIXME uggly
            self.cfg, is_train=False
        )
        if cfg.TEST.MODEL_FILE:
            self.model.load_state_dict(
                torch.load(cfg.TEST.MODEL_FILE, map_location=self.device), strict=True
            )
        self.model.to(self.device)

        # taken from DEKR/tools/inference_demo.py
        self.transforms = T.Compose(
            [
                T.ToTensor(),
                T.Normalize(  # FIXME values to adapt according to dataset
                    mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]
                ),
            ]
        )

    def train(self): # TODO
        pass
    
    def pre_process(self, image: torch.Tensor):
        # maybe check if the image should be by batch of alone
        # image = image[0]
        image = image.detach().cpu().numpy()  # tensor -> numpy
        image = np.transpose(image, (1, 2, 0))  # type: ignore # -> (H, W, 3)
        initial_shape = image.shape[:2]
        if image.shape[0] > image.shape[1]: # H > W
            ratio = float(self.cfg.DATASET.INPUT_SIZE) / float(image.shape[1])
            dim = (self.cfg.DATASET.INPUT_SIZE, int(ratio * image.shape[0]))
            image = cv2.resize(
                image, dim, interpolation=cv2.INTER_LINEAR  # type: ignore
            )  # -> (h, w, 3)
        else:
            ratio = float(self.cfg.DATASET.INPUT_SIZE) / float(image.shape[0])
            dim = (int(ratio * image.shape[1]), self.cfg.DATASET.INPUT_SIZE)
            image = cv2.resize(
                image, dim, interpolation=cv2.INTER_LINEAR  # type: ignore
            )  # -> (h, w, 3)
        reshaped_shape = image.shape[:2]
        return (image, initial_shape, reshaped_shape)
    
    @torch.no_grad() # FIXME for the moment it is required...
    def process(self, image):
        (image, initial_shape, reshaped_shape) = image
        # make inference and extract results
        base_size, center, scale = get_multi_scale_size(
            image, self.cfg.DATASET.INPUT_SIZE, 1.0, 1.0
        )
        heatmap_sum = 0
        poses = []

        for scale in sorted(self.cfg.TEST.SCALE_FACTOR, reverse=True):
            image_resized, center, scale_resized = resize_align_multi_scale(
                image, self.cfg.DATASET.INPUT_SIZE, scale, 1.0
            )

            image_resized = self.transforms(image_resized)
            image_resized = image_resized.unsqueeze(0).to(self.device)

            heatmap, posemap = get_multi_stage_outputs(
                self.cfg, self.model, image_resized, self.cfg.TEST.FLIP_TEST
            )
            heatmap_sum, poses = aggregate_results(
                self.cfg, heatmap_sum, poses, heatmap, posemap, scale
            )

        heatmap_avg = heatmap_sum / len(self.cfg.TEST.SCALE_FACTOR)
        poses, scores = pose_nms(self.cfg, heatmap_avg, poses)

        results_poses = []
        results_scores = []
        if scores:
            if self.cfg.TEST.MATCH_HMP:
                poses = match_pose_to_heatmap(self.cfg, poses, heatmap_avg)

            poses = get_final_preds(poses, center, scale_resized, base_size)
            if self.cfg.RESCORE.VALID:
                scores = rescore_valid(self.cfg, poses, scores)

            for score, pose in zip(scores, poses):
                if score >= self.cfg.TEST.vis_threshold:
                    results_scores.append(score)
                    results_poses.append(pose)
        results_scores = np.asarray(results_scores)
        results_poses = np.asarray(results_poses)
        
        # results_scores dropped
        return (results_poses, initial_shape, reshaped_shape)
    
    def post_process(self, results, metadata):
        (results_poses, initial_shape, reshaped_shape) = results
        detections = []
        for pose in results_poses:
            pose[:, :2] = rescale_keypoints(pose[:, :2], reshaped_shape, initial_shape)
            detections.append(
                Detection(
                    image_id = metadata.id,
                    video_id = metadata.video_id,
                    keypoints_xyc = pose,
                    bbox = kp_to_bbox(pose[:, :2]),
                    )  # type: ignore
            )
        return detections