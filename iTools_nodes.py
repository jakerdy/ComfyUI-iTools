import folder_paths
from pathlib import Path
import os
import torch
import numpy as np
import hashlib
import torchvision.transforms.v2 as T

import node_helpers
from PIL import Image, ImageSequence, ImageOps
from .metadata.shared import p
from .metadata.metadata_extractor import get_prompt
from .metadata.file_handeler import FileHandler
from .metadata.overlay import add_overlay_bar, img_to_tensor, add_underlay_bar
from .metadata.shared import styles
from .metadata.prompter import read_replace_and_combine, templates
from .metadata.prompter_multi import combine_multi, templates_basic, templates_extra1, templates_extra2, \
    templates_extra3
from .metadata.grid_filler import fill_grid_with_images_new, tensor_to_images, image_to_tensor


class IToolsLoadImagePlus:
    @classmethod
    def INPUT_TYPES(s):
        input_dir = folder_paths.get_input_directory()
        files = [f for f in os.listdir(input_dir) if os.path.isfile(os.path.join(input_dir, f))]
        return {"required":
                    {"image": (sorted(files), {"image_upload": True})},
                }

    CATEGORY = "iTools"

    RETURN_TYPES = ("IMAGE", "MASK", "STRING", "STRING")
    RETURN_NAMES = ("image", "mask", "possible prompt", "image name")
    FUNCTION = "load_image"
    DESCRIPTION = ("An enhancement of the original ComfyUI ImageLoader node. It attempts to return the possible prompt "
                   "used to create an image.")

    def load_image(self, image):
        image_path = folder_paths.get_annotated_filepath(image)
        filename = image.rsplit('.', 1)[0]  # get image name
        img = node_helpers.pillow(Image.open, image_path)

        output_images = []
        output_masks = []
        w, h = None, None

        excluded_formats = ['MPO']

        for i in ImageSequence.Iterator(img):
            i = node_helpers.pillow(ImageOps.exif_transpose, i)

            if i.mode == 'I':
                i = i.point(lambda i: i * (1 / 255))
            image = i.convert("RGB")

            if len(output_images) == 0:
                w = image.size[0]
                h = image.size[1]

            if image.size[0] != w or image.size[1] != h:
                continue

            image = np.array(image).astype(np.float32) / 255.0
            image = torch.from_numpy(image)[None,]
            if 'A' in i.getbands():
                mask = np.array(i.getchannel('A')).astype(np.float32) / 255.0
                mask = 1. - torch.from_numpy(mask)
            else:
                mask = torch.zeros((64, 64), dtype=torch.float32, device="cpu")
            output_images.append(image)
            output_masks.append(mask.unsqueeze(0))

        if len(output_images) > 1 and img.format not in excluded_formats:
            output_image = torch.cat(output_images, dim=0)
            output_mask = torch.cat(output_masks, dim=0)
        else:
            output_image = output_images[0]
            output_mask = output_masks[0]

        output_prompt = get_prompt(image_path)
        return (output_image, output_mask, output_prompt, filename)

    @classmethod
    def IS_CHANGED(s, image):
        image_path = folder_paths.get_annotated_filepath(image)
        m = hashlib.sha256()
        with open(image_path, 'rb') as f:
            m.update(f.read())
        return m.digest().hex()

    @classmethod
    def VALIDATE_INPUTS(s, image):
        if not folder_paths.exists_annotated_filepath(image):
            return "Invalid image file: {}".format(image)

        return True


class IToolsPromptLoader:

    @classmethod
    def INPUT_TYPES(s):
        return {"required":
            {
                "file_path": ("STRING", {"default": 'prompts.txt', "multiline": False}),
                "seed": ("INT", {"default": 0, "control_after_generate": 0, "min": 0, "max": 0xffff}),
            }
        }

    CATEGORY = "iTools"

    RETURN_TYPES = ("STRING", "INT")
    RETURN_NAMES = ("prompt", "count")
    FUNCTION = "load_file"
    DESCRIPTION = ("Will return a prompt (line number) from txt file at given "
                   "index, note that count start from zero.")

    def load_file(self, file_path, seed, fallback="Yes"):
        prompt = ""
        count = 0
        if file_path == "prompts.txt":
            file = os.path.join(p, "ComfyUI-iTools", "examples", "prompts.txt")
        else:
            file = file_path.replace('"', '')
        if os.path.exists(file):
            fh = FileHandler(file)
            try:
                count = fh.len_lines()
                line = fh.read_line(seed)
                prompt = fh.unescape_quotes(line)
            except IndexError:
                if fallback == "Yes":
                    seed = seed % fh.len_lines()
                    line = fh.read_line(seed)
                    prompt = fh.unescape_quotes(line)
        else:
            prompt = f"File not exist, {file}"
        return prompt, count


class IToolsPromptSaver:
    @classmethod
    def INPUT_TYPES(s):
        return {"required":
                    {"prompt": ("STRING", {"forceInput": True}),
                     "file_path": ("STRING", {"default": 'prompts.txt', "multiline": False}),
                     }
                }

    CATEGORY = "iTools"
    RETURN_TYPES = ()
    OUTPUT_NODE = True
    FUNCTION = "save_to_file"
    DESCRIPTION = "Will append the given prompt as a new line to the given txt file"

    def save_to_file(self, file_path, prompt):
        if file_path == "prompts.txt":
            file = os.path.join(p, "ComfyUI-iTools", "examples", "prompts.txt")
        else:
            file = file_path.replace('"', '')
        if os.path.exists(file) and prompt is not None and prompt != "":
            fh = FileHandler(file)
            try:
                fh.append_line(prompt)
                print(f"Prompt: {prompt} saved to {file}")
            except Exception as e:
                print(f"Error while writing the prompt: {e}")
        else:
            print(f"Error while writing the prompt")
        return (True,)


class IToolsPromptStyler:

    def __init__(self):
        # self.comfyClass = "iTools Prompt Styler"
        pass

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "text_positive": ("STRING", {"default": "", "multiline": True}),
                "text_negative": ("STRING", {"default": "", "multiline": True}),
                "style_file": ((styles), {"default": "basic.yaml"}),
                "template_name": ((templates),),
            },
        }

    @classmethod
    def VALIDATE_INPUTS(s, template_name):
        # YOLO, anything goes!
        return True

    RETURN_TYPES = ('STRING', 'STRING',)
    RETURN_NAMES = ('positive_prompt', 'negative_prompt',)
    FUNCTION = 'prompt_styler'
    CATEGORY = 'iTools'
    DESCRIPTION = ("Helps you quickly populate your prompt using a template stored in YAML file.")

    def prompt_styler(self, text_positive, text_negative, template_name, style_file):
        positive_prompt, negative_prompt = read_replace_and_combine(template_name, text_positive,
                                                                    text_negative, style_file)
        return positive_prompt, negative_prompt


class IToolsAddOverlay:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required":
            {
                "image": ("IMAGE", {}),
                "text": ("STRING", {"default": 'img info:', "multiline": False}),
                "background_color": ("STRING", {"default": '#000000AA', "multiline": False}),
                "font_size": ("INT", {"default": 40, "min": 10, "max": 1000}),
                "overlay_mode": ("BOOLEAN", {"default": True}),
            }
        }

    CATEGORY = "iTools"
    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    # OUTPUT_NODE = True
    FUNCTION = "add_text_overlay"
    DESCRIPTION = ("Will add an overlay bottom bar to show a given text, you may change the background color of the "
                   "overlay bar and the font size.")

    def add_text_overlay(self, image, text, font_size, background_color, overlay_mode):
        # Remove the batch dimension and rearrange to [C, H, W]
        tensor = image.squeeze(0).permute(2, 0, 1)

        # Ensure the values are in the range [0, 1]
        tensor = tensor.clamp(0, 1)

        # Convert to PIL Image
        to_pil = T.ToPILImage()
        pil_image = to_pil(tensor)

        # Add overlay or underlay
        if overlay_mode:
            composite = add_overlay_bar(pil_image, text, font_size=font_size, background_color=background_color)
        else:
            composite = add_underlay_bar(pil_image, text, font_size=font_size, background_color=background_color)

        # Convert back to tensor
        to_tensor = T.ToTensor()
        out = to_tensor(composite)

        # Add batch dimension to match original input
        out = out.unsqueeze(0)

        # Rearrange back to [B, H, W, C] to match input format
        out = out.permute(0, 2, 3, 1)

        return (out,)


class IToolsLoadImages:
    @classmethod
    def INPUT_TYPES(s):
        return {"required": {
            "images_directory": ("STRING", {"multiline": False}),
            "start_index": ("INT", {"default": 0, "min": 0, "max": 200}),
            "load_limit": ("INT", {"default": 4, "min": 2, "max": 200})
        }}

    RETURN_TYPES = ('IMAGE', "STRING", "INT")
    RETURN_NAMES = ('images', 'images names', 'count')
    FUNCTION = 'load_images'
    CATEGORY = 'iTools'
    OUTPUT_IS_LIST = (True, True, False)
    DESCRIPTION = ("Will return list of images from a given directory with a given limit, for example if the limit is "
                   "4 it will return first 4 images in that directory. it will also return the list of these images "
                   "names.")

    def load_images(self, images_directory, load_limit, start_index):
        image_extensions = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.gif'}

        images_path = Path(images_directory.replace('"', ''))
        if not images_path.exists():
            raise FileNotFoundError(f"Image directory {images_directory} does not exist")

        images = []
        images_names = []
        for idx, image_path in enumerate(images_path.iterdir()):
            if idx < start_index:
                continue  # Skip images until reaching the start_index
            if image_path.suffix.lower() in image_extensions:
                images.append(img_to_tensor(Image.open(image_path)))
                images_names.append(image_path.stem)  # Add the image name without extension
                if len(images) >= load_limit:
                    break

        return images, images_names, len(images)


class IToolsPromptStylerExtra:

    def __init__(self):
        pass

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "text_positive": ("STRING", {"default": "", "multiline": True}),
                "text_negative": ("STRING", {"default": "", "multiline": True}),
                "base_file": ((styles), {"default": "basic.yaml"}),
                "base_style": ((templates_basic),),
                "second_file": ((styles), {"default": "camera.yaml"}),
                "second_style": ((templates_extra1),),
                "third_file": ((styles), {"default": "artist.yaml"}),
                "third_style": ((templates_extra2),),
                "fourth_file": ((styles), {"default": "mood.yaml"}),
                "fourth_style": ((templates_extra3),),
            },
        }

    @classmethod
    def VALIDATE_INPUTS(s,
                        base_style,
                        second_style,
                        third_style,
                        fourth_style):
        # YOLO, anything goes!
        return True

    RETURN_TYPES = ('STRING', 'STRING',)
    RETURN_NAMES = ('positive_prompt', 'negative_prompt',)
    FUNCTION = 'prompt_styler_extra'
    CATEGORY = 'iTools'
    DESCRIPTION = ("Helps you quickly populate your prompt using templates from up to 4 YAML files.")

    def prompt_styler_extra(self, text_positive, text_negative,
                            base_file, base_style,
                            second_file, second_style,
                            third_file, third_style,
                            fourth_file, fourth_style,
                            ):
        positive_prompt, negative_prompt = combine_multi(
            text_positive, text_negative,
            base_file, base_style,
            second_file, second_style,
            third_file, third_style,
            fourth_file,
            fourth_style, )  # (read_replace_and_combine_multi(template_name, text_positive,text_negative, style_file))
        return positive_prompt, negative_prompt


class IToolsGridFiller:

    @classmethod
    def INPUT_TYPES(cls):
        return {"required":
            {
                "images": ("IMAGE", {}),
                "width": ("INT", {"default": 1024, "min": 512, "max": 8192}),
                "height": ("INT", {"default": 1024, "min": 512, "max": 8192}),
                "rows": ("INT", {"default": 3, "min": 2, "max": 10}),
                "cols": ("INT", {"default": 3, "min": 2, "max": 10}),
                "gaps": ("FLOAT", {"default": 2, "min": 0.0, "max": 50, "steps": 1}),
                "background_color": ("STRING", {"default": '#000000AA', "multiline": False}),
            }
        }

    RETURN_TYPES = ('IMAGE',)
    RETURN_NAMES = ('images',)
    FUNCTION = 'fill_grid'
    CATEGORY = 'iTools'
    INPUT_IS_LIST = (True, False, False, False, False, False, False)
    OUTPUT_IS_LIST = (False, False, False, False, False, False, False)
    DESCRIPTION = ("Arranging a set of images into specified rows and columns, applying "
                   "optional spacing and background color")

    def fill_grid(self, images, width, height, rows, cols, gaps, background_color):
        print("IMAGES", images)
        # Convert tensor to Pillow images
        pillow_images = tensor_to_images(images)

        # Process images using the provided function
        processed_image = fill_grid_with_images_new(pillow_images, rows=rows, cols=cols, grid_size=(width, height),
                                                gap=gaps,
                                                bg_color=background_color)

        # Convert the processed Pillow image back to a tensor
        output_tensor = image_to_tensor(processed_image)

        return (output_tensor,)


class IToolsLineLoader:

    @classmethod
    def INPUT_TYPES(s):
        return {"required":
            {
                "lines": ("STRING", {"default": 'cat\ndog\nbunny', "multiline": True}),
                "seed": ("INT", {"default": 0, "control_after_generate": "increment", "min": 0, "max": 0xfff}),
            }
        }

    CATEGORY = "iTools"

    RETURN_TYPES = ("STRING", "INT")
    RETURN_NAMES = ("line loaded", "count")
    FUNCTION = "load_line"
    DESCRIPTION = ("Will return a line from a multi line text at given "
                   "index, note that count start from zero.")

    def load_line(self, lines, seed, fallback="Yes"):
        # Split the multiline string into individual lines
        line_list = lines.splitlines()

        # Count the total number of lines
        count = len(line_list)

        # Check if the seed index is valid
        if 0 <= seed < count:
            line = line_list[seed]
        elif fallback == "Yes" and count > 0:
            # If fallback is "Yes", mod the seed by the line count to wrap around
            seed_mod = seed % count
            line = line_list[seed_mod]
        else:
            # If the index is out of range and no fallback, return an empty string
            line = ""

        return line, count


class IToolsTextReplacer:

    @classmethod
    def INPUT_TYPES(s):
        return {"required":
            {
                "text_in": ("STRING", {"forceInput": True, "multiline": False}),
                "match": ("STRING", {"forceInput": False, "multiline": False}),
                "replace": ("STRING", {"forceInput": False, "multiline": False}),
            }
        }

    CATEGORY = "iTools"

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("text_out",)
    FUNCTION = "replace_text"
    DESCRIPTION = "Help you replace a match in a given text."

    def replace_text(self, text_in, match, replace):
        print(text_in)
        return text_in.replace(match, replace),


# A dictionary that contains all nodes you want to export with their names
# NOTE: names should be globally unique
NODE_CLASS_MAPPINGS = {
    "iToolsLoadImagePlus": IToolsLoadImagePlus,
    "iToolsPromptLoader": IToolsPromptLoader,
    "iToolsPromptSaver": IToolsPromptSaver,
    "iToolsAddOverlay": IToolsAddOverlay,
    "iToolsLoadImages": IToolsLoadImages,
    "iToolsPromptStyler": IToolsPromptStyler,
    "iToolsPromptStylerExtra": IToolsPromptStylerExtra,
    "iToolsGridFiller": IToolsGridFiller,
    "iToolsLineLoader": IToolsLineLoader,
    "iToolsTextReplacer": IToolsTextReplacer,
}

# A dictionary that contains the friendly/humanly readable titles for the nodes
NODE_DISPLAY_NAME_MAPPINGS = {
    "iToolsLoadImagePlus": "iTools Load Image Plus",
    "iToolsPromptLoader": "iTools Prompt Loader",
    "iToolsPromptSaver": "iTools Prompt Saver",
    "iToolsAddOverlay": "iTools Add Text Overlay",
    "iToolsLoadImages": "iTools Load Images 📦",
    "iToolsPromptStyler": "iTools Prompt Styler 🖌️",
    "iToolsPromptStylerExtra": "iTools Prompt Styler Extra 🖌️",
    "iToolsGridFiller": "iTools Grid Filler 📲",
    "iToolsLineLoader": "iTools Line Loader",
    "iToolsTextReplacer": "iTools Text Replacer"
}
