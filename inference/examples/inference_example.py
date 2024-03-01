from inference import *


video_path = "/path/video.mp4"
video_path = "/home/celine/pb-small/pb-track/inference/video_files/openpifpaf.mp4"
output_json_path = '/path/result.json'
output_json_path = "/home/celine/pb-small/pb-track/inference/video_files/testest.json"

output_video_path = '/path/video_result.mp4'
output_video_path = "/home/celine/pb-small/pb-track/inference/video_files/openpifpafjsp.mp4"

if __name__ == "__main__":

    test = VideoInference(video_path=video_path)
    test.add_model(['openpifpaf', 'bytetrack_sort'])

    print(test.pipeline)

    #output_json can be None
    test.process_video(output_json=output_json_path)

    test.visualization(video_path=output_video_path)
