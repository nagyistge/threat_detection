import os
import cStringIO
import time
import argparse
import numpy as np
import pandas as pd
from skimage.io import imsave
import skimage.io as skimage_io
import json

# custom scripts:
import gabor_features
import resize_image
import base64

# OpenCV:
import cv2

from pysparkling import Context
# from pyspark import SparkContext, SparkConf

import multiprocessing
from functools import partial



def image_processing_cstringio(cstring_object, num_rows, num_cols):
    resized_filename = resize_image.resize_image_ocr_cstringio(cstring_object, num_rows, num_cols)

    #OpenCV addition:
    # ----------------------
    img = cv2.imread(resized_filename,0)
    img = cv2.medianBlur(img,3)

    (thresh, im_bw) = cv2.threshold(img, 128, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)

    im_adaptive_filename = cStringIO.StringIO()
    imsave(im_adaptive_filename, im_bw)
    return im_adaptive_filename


def resize_image_and_get_full_gabor_features(cstring_image_obj, num_rows, num_cols):
    resized_filename = resize_image.resize_image_cstringio(cstring_image_obj, num_rows, num_cols)
    num_levels = 3
    num_orientations = 8
    gabor_features_vec = gabor_features.get_gabor_features_texture_classification(resized_filename, num_levels, num_orientations)
    print 'Dimension of gabor feature vec is %d' % gabor_features_vec.shape[1]
    # print type(gabor_features_vec)
    print gabor_features_vec.shape
    return gabor_features_vec

def get_hog_features(cstring_image_obj):
    # file_full_path = cstring_image_obj.read()
    bin_n = 16
    img = skimage_io.imread(cstring_image_obj)
    # print img.size
    # img = cv2.cvtColor(img,cv2.COLOR_BGR2GRAY)
    gx = cv2.Sobel(img, cv2.CV_32F, 1, 0)
    gy = cv2.Sobel(img, cv2.CV_32F, 0, 1)
    mag, ang = cv2.cartToPolar(gx, gy)

    # quantizing binvalues in (0...16)
    bins = np.int32(bin_n*ang/(2*np.pi))

    # Divide to 4 sub-squares
    img_shape = bins.shape
    num_rows = img_shape[0]
    num_cols = img_shape[1]

    # Below 4 squares:
    # Top-left, bottom-left, top-right, bottom-right
    # bin_cells = bins[:10,:10], bins[10:,:10], bins[:10,10:], bins[10:,10:]
    # mag_cells = mag[:10,:10], mag[10:,:10], mag[:10,10:], mag[10:,10:]
    row_bound_1 = (num_rows/2) + int(0.1*(num_rows/2))
    row_bound_2 = (num_rows/2) - int(0.1*(num_rows/2))
    col_bound_1 = (num_cols/2) + int(0.1*(num_cols/2))
    col_bound_2 = (num_cols/2) - int(0.1*(num_cols/2))
    bin_cells = bins[:row_bound_1, :col_bound_1], bins[row_bound_2:, :col_bound_1], bins[:row_bound_1, col_bound_2:], bins[row_bound_2:, col_bound_2:]
    mag_cells = mag[:row_bound_1, :col_bound_1], mag[row_bound_2:, :col_bound_1], mag[:row_bound_1, col_bound_2:], mag[row_bound_2:, col_bound_2:]
    hists = [np.bincount(b.ravel(), m.ravel(), bin_n) for b, m in zip(bin_cells, mag_cells)]
    hist = np.hstack(hists)

    # 2nd derivative:
    gx = cv2.Sobel(img, cv2.CV_32F, 2, 0)
    gy = cv2.Sobel(img, cv2.CV_32F, 0, 2)
    mag, ang = cv2.cartToPolar(gx, gy)

    # quantizing binvalues in (0...16)
    bins = np.int32(bin_n * ang / (2 * np.pi))

    # Divide to 4 sub-squares
    # Below 4 squares:
    # Top-left, bottom-left, top-right, bottom-right
    bin_cells = bins[:row_bound_1, :col_bound_1], bins[row_bound_2:, :col_bound_1], bins[:row_bound_1,col_bound_2:], bins[row_bound_2:,col_bound_2:]
    mag_cells = mag[:row_bound_1, :col_bound_1], mag[row_bound_2:, :col_bound_1], mag[:row_bound_1, col_bound_2:], mag[row_bound_2:,col_bound_2:]
    hists = [np.bincount(b.ravel(), m.ravel(), bin_n) for b, m in zip(bin_cells, mag_cells)]
    hist2 = np.hstack(hists)
    hist_two_deriv = np.hstack((hist, hist2))

    print 'HOG feature vector shape:'
    print hist_two_deriv.shape
    return hist_two_deriv

def serialize(subdir, file_i):
    file_full_path = os.path.join(subdir, file_i)
    f = open(file_full_path, 'r').read()
    byte_data = base64.b64encode(f)
    dict = {}
    dict["name"] = file_full_path
    dict["bytes"] = byte_data
    print '----SERIALIZING----'
    return json.dumps(dict)

def serialize_and_make_df(image_dir_path):
    for subdir, dirs, files in os.walk(image_dir_path):
        try:
            cpus = multiprocessing.cpu_count()
        except NotImplementedError:
            cpus = 2
        pool = multiprocessing.Pool(processes=cpus)
        # print pool.map(serialize, files)
        func = partial(serialize, subdir)
        data = pool.map(func, files)
        return data

def dump(x):
    return json.dumps(x)

# Returns hog and gist feature vector as a list
# If features cannot be extracted from image, return
# sentinel vector - a list of -1's, [-1, -1, ..., -1]
def get_hog_and_gist_feats(bytes_str, num_rows, num_cols):
    img_data = str(base64.b64decode(bytes_str))
    cstring_image_obj = cStringIO.StringIO(img_data)
    try:
        hog_features_vec = get_hog_features(cstring_image_obj)
        gabor_features_vec = resize_image_and_get_full_gabor_features(cstring_image_obj, num_rows, num_cols)
        gabor_features_vec = gabor_features_vec.reshape(gabor_features_vec.shape[1], 1)
        supp_feat_vec = np.vstack((gabor_features_vec, hog_features_vec.reshape(hog_features_vec.shape[0], 1)))
        # print 'Full vec shape is:'
        # print supp_feat_vec.shape
        return supp_feat_vec.flatten().tolist()
    except Exception as e:
        print e
        # print("ERROR reading image file %s" % str(bytes_str))
        print
        CURR_NUM_FEATURES = 152
        sentinel_vec = -1*np.ones(CURR_NUM_FEATURES)
        return sentinel_vec.tolist()


def get_features(image_json_txt_obj):
    print '---------------PROCESSING IMAGE----------------'
    image_json_dict = json.loads(image_json_txt_obj)
    bytes_str = str(image_json_dict["bytes"])
    num_rows = num_cols = 100
    features = get_hog_and_gist_feats(bytes_str, num_rows, num_cols)
    image_json_dict["features"] = features
    # debugging:
    image_json_dict["bytes"] = ""
    return image_json_dict

# For each image file submitted for processing,
# saves features and corresponding filename as json object
# ------------------------------------------
# NOTE: for each json object in output, check first element of "features" list for -1.
# If equals -1, then method was unable to extract features from the image
def run_feature_extraction():
    start_time = time.time()
    desc='Feature Extraction for Images'
    parser = argparse.ArgumentParser(
        description=desc,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=desc)

    default_path = 'target_images'
    parser.add_argument("--input_dir", help="input directory", default=default_path)
    parser.add_argument("--output", help="output file", default='image_features')
    args = parser.parse_args()
    # serialize and put all images in rdd:
    # use json schema:
    #     "name": "",
    #     "bytes": ""
    #     "features": "[]"
    image_dir_path = args.input_dir
    data_arr = serialize_and_make_df(image_dir_path)

    # pysparkling:
    sc = Context()

    # pyspark:
    # conf = SparkConf().setAppName("HOG and GIST ETL")
    # sc = SparkContext(conf=conf)

    num_parts = 100
    rdd = sc.parallelize(data_arr, num_parts)
    # submit image rdd to processing
    rdd_features = rdd.map(get_features)
    # save as txt file:
    rdd_features.map(dump).coalesce(1).saveAsTextFile(args.output)
    print "------------------ %f minutes elapsed ------------------------" % ((time.time() - start_time)/60.0)


if __name__ == '__main__':
    run_feature_extraction()
