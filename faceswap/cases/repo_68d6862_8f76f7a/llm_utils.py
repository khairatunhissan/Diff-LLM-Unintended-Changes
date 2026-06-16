'''
Multiple plaidml implementation.
'''
from plaidml.keras import backend as K


extract_image_patches = K.extract_image_patches  # pylint: disable=invalid-name
pad = K.pad