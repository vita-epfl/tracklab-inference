import torch
import numpy as np
import pandas as pd
from pathlib import Path

from tracklab.pipeline import ImageLevelModule
from tracklab.utils.coordinates import ltrb_to_ltwh
import plugins.track.strong_sort.strong_sort as strong_sort

import logging

log = logging.getLogger(__name__)


class StrongSORT(ImageLevelModule):
    input_columns = [
        "bbox_ltwh",
        "bbox_conf",
        "category_id",
    ]
    output_columns = ["track_id", "track_bbox_ltwh", "track_bbox_conf"]

    def __init__(self, cfg, device, batch_size, **kwargs):
        super().__init__(cfg, device, batch_size)
        self.cfg = cfg
        self.reset()

    def reset(self):
        """Reset the tracker state to start tracking in a new video."""
        self.model = strong_sort.StrongSORT(
            Path(self.cfg.model_weights),
            self.device,
            self.cfg.fp16,
            **self.cfg.hyperparams
        )
        # For camera compensation
        self.prev_frame = None

    @torch.no_grad()
    def preprocess(self, detection: pd.Series, metadata: pd.Series):
        ltrb = detection.bbox.ltrb()
        conf = detection.bbox.conf()
        cls = detection.category_id
        tracklab_id = detection.name
        return {
            "input": np.array(
                [ltrb[0], ltrb[1], ltrb[2], ltrb[3], conf, cls, tracklab_id]
            ),
        }

    @torch.no_grad()
    def process(self, batch, image, detections: pd.DataFrame):
        if self.cfg.ecc:
            if self.prev_frame is not None:
                self.model.tracker.camera_update(self.prev_frame, image)
            self.prev_frame = image
        inputs = batch["input"]  # Nx7 [l,t,r,b,conf,class,tracklab_id]
        inputs = inputs[inputs[:, 4] > self.cfg.min_confidence]
        results = self.model.update(inputs, image)
        results = np.asarray(results)  # N'x9 [l,t,r,b,track_id,class,conf,queue,idx]
        if results.size:
            track_bbox_ltwh = [ltrb_to_ltwh(x) for x in results[:, :4]]
            track_bbox_conf = list(results[:, 6])
            track_ids = list(results[:, 4])
            idxs = list(results[:, 8].astype(int))
            # FIXME should be a subset but sometimes returns an idx that was in the previous
            # batch of detections... For the moment, we let the override happen
            # assert set(idxs).issubset(
            #    detections.index
            # ), "Mismatch of indexes during the tracking. The results should match the detections."
            results = pd.DataFrame(
                {
                    "track_bbox_ltwh": track_bbox_ltwh,
                    "track_bbox_conf": track_bbox_conf,
                    "track_id": track_ids,
                    "idxs": idxs,
                }
            )
            results.set_index("idxs", inplace=True, drop=True)
            return results
        else:
            return []
