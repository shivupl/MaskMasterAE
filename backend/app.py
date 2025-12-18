from flask import Flask, request, send_file
from rembg import remove, new_session
from PIL import Image
from flask_cors import CORS
import io
import os
import cv2
import numpy as np
import imageio.v2 as imageio
import tempfile
import shutil
import subprocess
import json


app = Flask(__name__)


session = new_session(model_name="u2netp")  # Options: u2net, u2netp, u2net_human_seg, isnet-general-use

# CORS(app, resources={r"/*": {"origins": ["https://express.adobe.com", "http://localhost:5241"]}})
CORS(app, supports_credentials=True, resources={r"/*": {"origins": "*"}})


@app.route("/process", methods=["POST", "OPTIONS"])
def process_image():
    print("checkpt1")
    if "image" not in request.files:
        return {"error": "No image uploaded"}, 400

    uploaded_file = request.files["image"]
    print("checkpt2")
    try:
        input_image = Image.open(uploaded_file.stream).convert("RGBA")
        print("checkpt3")

        # Convert image to NumPy array
        data = np.array(input_image)

        # Define threshold for "white" (tweak if needed)
        white_thresh = 240
        white_mask = np.all(data[:, :, :3] >= white_thresh, axis=2)

        # Set alpha to 0 where white
        data[white_mask] = [255, 255, 255, 0]

        # Create new image from modified array
        output_image = Image.fromarray(data)

        print("checkpt4")
        img_io = io.BytesIO()
        output_image.save(img_io, format="PNG")
        img_io.seek(0)


        print("checkpt5")

        return send_file(
            img_io,
            mimetype="image/png",
            as_attachment=False,
        )

    except Exception as e:
        return {"error": str(e)}, 500



@app.route("/mask-video", methods=["POST"])
def mask_video():
    try:
        # Check uploads
        if "foreground" not in request.files or "background" not in request.files:
            return {"error": "Missing one or more files"}, 400

        mask_file = request.files["foreground"]
        video_file = request.files["background"]

        # Load the mask (from memory)
        mask_img = Image.open(mask_file.stream).convert("RGBA")
        alpha = mask_img.getchannel("A")
        mask_np = np.array(alpha) > 0
        W, H = mask_img.size

        # Use temporary files for video processing
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_video, \
             tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_output:

            shutil.copyfileobj(video_file.stream, tmp_video)
            tmp_video.flush()

            cap = cv2.VideoCapture(tmp_video.name)
            if not cap.isOpened():
                raise ValueError("Could not open uploaded video")

            fps = cap.get(cv2.CAP_PROP_FPS)
            writer = imageio.get_writer(tmp_output.name, fps=fps)

            while True:
                ret, frame = cap.read()
                if not ret:
                    break

                frame = cv2.resize(frame, (W, H))
                frame_rgba = cv2.cvtColor(frame, cv2.COLOR_BGR2BGRA)
                frame_rgba[~mask_np] = (0, 0, 0, 0)
                output_bgr = cv2.cvtColor(frame_rgba, cv2.COLOR_BGRA2BGR)
                writer.append_data(output_bgr)

            cap.release()
            writer.close()

            return send_file(tmp_output.name, mimetype="video/mp4")

    except Exception as e:
        import traceback
        print("error:", traceback.format_exc())
        return {"error": str(e)}, 500
    


@app.route("/mask-image", methods=["POST", "OPTIONS"])
def mask_image():
    if "foreground" not in request.files or "background" not in request.files:
        return {"error": "Missing one or more images"}, 400

    # Load uploaded files
    foreground_file = request.files["foreground"]
    background_file = request.files["background"]

    try:
        # Load images into PIL
        object_img = Image.open(foreground_file.stream).convert("RGBA")
        background_img = Image.open(background_file.stream).convert("RGBA")

        # Resize background to match foreground
        background_img = background_img.resize(object_img.size)

        # Apply alpha mask from foreground
        alpha = object_img.getchannel("A")
        transparent = Image.new("RGBA", object_img.size, (0, 0, 0, 0))
        result = Image.composite(background_img, transparent, alpha)

        # Save result to memory
        img_io = io.BytesIO()
        result.save(img_io, format="PNG")
        img_io.seek(0)

        return send_file(img_io, mimetype="image/png")

    except Exception as e:
        return {"error": str(e)}, 500


@app.route("/outter-mask-image", methods=["POST"])
def outter_mask_image():
    if "foreground" not in request.files or "color" not in request.form:
        return {"error": "Missing image or color"}, 400

    fg_file = request.files["foreground"]
    color_str = request.form["color"]
    rgba = json.loads(color_str)

    try:
        object_img = Image.open(fg_file.stream).convert("RGBA")
        alpha = object_img.getchannel("A")

        background = Image.new("RGBA", object_img.size, tuple(rgba))
        transparent = Image.new("RGBA", object_img.size, (0, 0, 0, 0))

        result = Image.composite(transparent, background, alpha)

        img_io = io.BytesIO()
        result.save(img_io, format="PNG")
        img_io.seek(0)

        return send_file(img_io, mimetype="image/png")

    except Exception as e:
        return {"error": str(e)}, 500

@app.route("/outer-mask-image-with-bg", methods=["POST"])
def outer_mask_image_with_bg():
    if "foreground" not in request.files or "background" not in request.files:
        return {"error": "Missing one or more images"}, 400

    fg_file = request.files["foreground"]
    bg_file = request.files["background"]

    try:
        object_img = Image.open(fg_file.stream).convert("RGBA")
        background_img = Image.open(bg_file.stream).convert("RGBA")

        # Match sizes
        background_img = background_img.resize(object_img.size)

        alpha = object_img.getchannel("A")
        transparent = Image.new("RGBA", object_img.size, (0, 0, 0, 0))

        # Outer mask: inside object = transparent, outside = background image
        result = Image.composite(transparent, background_img, alpha)

        img_io = io.BytesIO()
        result.save(img_io, format="PNG")
        img_io.seek(0)

        return send_file(img_io, mimetype="image/png")

    except Exception as e:
        return {"error": str(e)}, 500



if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)

