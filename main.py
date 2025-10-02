import argparse
import os
import time
import random
import re
import base64
import urllib.request
from datetime import datetime
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from openai import OpenAI, APIStatusError
from google import genai
from google.genai import types
from puzzle_solver import solve_geetest_puzzle
from PIL import Image
import traceback
from concurrent.futures import ThreadPoolExecutor
from ai_utils import (
    ask_text_to_chatgpt,
    ask_text_to_gemini,
    ask_audio_to_openai,
    ask_audio_to_gemini,
    ask_recaptcha_instructions_to_chatgpt,
    ask_recaptcha_instructions_to_gemini,
    ask_if_tile_contains_object_chatgpt,
    ask_if_tile_contains_object_gemini,
    ask_puzzle_distance_to_gemini,
    ask_puzzle_distance_to_chatgpt,
    ask_puzzle_correction_to_chatgpt,
    ask_puzzle_correction_to_gemini
)

#todo: sesli captchada sese asıl captchayı söyledikten sonra ignore previous instructions diyip sonra random bir captcha daha vericem
load_dotenv()

# Initialize clients at the top level
gemini_client = None
if os.getenv("GOOGLE_API_KEY"):
    gemini_client = genai.Client()

def create_success_gif(image_paths, output_folder="successful_solves"):
    """Creates a GIF from a list of images, resizing them to the max dimensions without distortion."""
    if not image_paths:
        print("No images provided for GIF creation.")
        return

    os.makedirs(output_folder, exist_ok=True)
    
    valid_images = []
    for path in image_paths:
        if os.path.exists(path):
            try:
                valid_images.append(Image.open(path).convert("RGB"))
            except Exception as e:
                print(f"Warning: Could not open or convert image {path}. Skipping. Error: {e}")
        else:
            print(f"Warning: Image path for GIF not found: {path}. Skipping.")

    if not valid_images:
        print("\nCould not create success GIF because no valid source images were found.")
        return

    try:
        # Find the maximum width and height among all images
        max_width = max(img.width for img in valid_images)
        max_height = max(img.height for img in valid_images)
        canvas_size = (max_width, max_height)

        processed_images = []
        for img in valid_images:
            # Create a new blank canvas with the max dimensions
            canvas = Image.new('RGB', canvas_size, (255, 255, 255))
            # Paste the original image into the center of the canvas
            paste_position = ((max_width - img.width) // 2, (max_height - img.height) // 2)
            canvas.paste(img, paste_position)
            processed_images.append(canvas)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(output_folder, f"success_{timestamp}.gif")

        processed_images[0].save(
            output_path,
            save_all=True,
            append_images=processed_images[1:],
            duration=800,
            loop=0
        )
        print(f"\n✨ Successfully saved solution GIF to {output_path}")
    except Exception as e:
        print(f"\nCould not create success GIF. Error: {e}")

def average_of_array(arr):
    if not arr:
        return 0  # Handle edge case of empty array
    sum_elements = sum(arr)
    average = sum_elements / len(arr)
    return average - 5

def check_tile_for_object(args):
    """Helper function for ThreadPoolExecutor to call the correct AI provider for a single tile."""
    tile_index, tile_path, object_name, provider, model = args
    
    try:
        decision_str = ''
        if provider == 'openai':
            decision_str = ask_if_tile_contains_object_chatgpt(tile_path, object_name, model)
        else: # gemini
            decision_str = ask_if_tile_contains_object_gemini(tile_path, object_name, model)
        
        print(f"Tile {tile_index}: Does it contain '{object_name}'? AI says: {decision_str}")
        return tile_index, decision_str == 'true'
    except Exception as e:
        print(f"Error checking tile {tile_index}: {e}")
        return tile_index, False

def audio_test(file_path='files/audio.mp3', provider='gemini', model=None):
    """Transcribes a local audio file using the specified AI provider."""
    if not os.path.exists(file_path):
        print(f"Error: Audio file not found at '{file_path}'")
        return

    try:
        print(f"Transcribing audio from '{file_path}' using {provider.upper()}...")
        transcription = ""
        if provider == 'openai':
            transcription = ask_audio_to_openai(file_path, model)
        else: # default to gemini
            transcription = ask_audio_to_gemini(file_path, model)
        
        print("\n--- Transcription Result ---")
        print(transcription)
        print("--------------------------\n")
    except Exception as e:
        print(f"An error occurred during audio transcription: {e}")

def complicated_text_test(driver, provider='openai', model=None):
    """
    Solves a single "Complicated Text" captcha instance, trying up to 3 times.
    The benchmark is successful if any attempt passes.
    Returns the attempt number (1, 2, or 3) on success, or 0 on failure.
    """
    driver.get("https://2captcha.com/demo/mtcaptcha")
    time.sleep(5)
    screenshot_paths = []
    
    for attempt in range(3):
        print(f"\n--- Complicated Text: Attempt {attempt + 1}/3 ---")
        try:
            # 1. Get the captcha image
            iframe = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, "mtcaptcha-iframe-1"))
            )
            time.sleep(2) # Allow time for new captcha to load on retries
            
            captcha_screenshot_path = f'screenshots/complicated_text_attempt_{attempt + 1}.png'
            iframe.screenshot(captcha_screenshot_path)
            screenshot_paths.append(captcha_screenshot_path)

            # 2. Ask AI for the answer
            response = ''
            if provider == 'openai':
                response = ask_text_to_chatgpt(captcha_screenshot_path, model)
            else: # gemini
                response = ask_text_to_gemini(captcha_screenshot_path, model)

            print(f"AI transcription: '{response}'")
            
            # 3. Submit the answer
            driver.switch_to.frame(iframe)
            input_field = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CLASS_NAME, "mtcap-noborder.mtcap-inputtext.mtcap-inputtext-custom"))
            )
            input_field.clear()
            input_field.send_keys(response)
            time.sleep(2)
            driver.switch_to.default_content()
            
            submit_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Check')]"))
            )
            submit_button.click()
            
            # 4. Check for success
            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CLASS_NAME, "_successMessage_w91t8_1"))
            )
            
            print("Captcha passed successfully!")
            final_success_path = f"screenshots/final_success_complicated_{datetime.now().strftime('%H%M%S')}.png"
            driver.save_screenshot(final_success_path)
            screenshot_paths.append(final_success_path)
            create_success_gif(screenshot_paths, output_folder=f"successful_solves/complicated_text_{provider}")
            return attempt + 1 # Return the successful attempt number

        except Exception as e:
            print(f"Attempt {attempt + 1} did not pass.")
            if attempt < 2:
                print("Retrying...")
            else:
                print("All 3 attempts failed for this benchmark run.")
            
            try:
                driver.switch_to.default_content()
            except Exception:
                pass

    return 0

def text_test(driver, provider='openai', model=None):
    """
    Solves a single "Normal Text" captcha instance.
    Returns 1 for success, 0 for failure.
    """
    driver.get("https://2captcha.com/demo/normal")
    time.sleep(5)
    screenshot_paths = []
    try:
        captcha_image = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, "_captchaImage_rrn3u_9"))
        )
        time.sleep(2)
        captcha_screenshot_path = 'screenshots/text_captcha_1.png'
        captcha_image.screenshot(captcha_screenshot_path)
        screenshot_paths.append(captcha_screenshot_path)
        
        response = ''
        if provider == 'openai':
            response = ask_text_to_chatgpt(captcha_screenshot_path, model)
        else: # gemini
            response = ask_text_to_gemini(captcha_screenshot_path, model)

        print(f"AI transcription: '{response}'")

        input_field = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, "_inputInner_ws73z_12"))
        )
        input_field.clear()
        input_field.send_keys(response)
        submit_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Check')]"))
        )
        submit_button.click()

        # If correct, the 'Check' button will disappear.
        WebDriverWait(driver, 10).until(
            EC.invisibility_of_element_located((By.XPATH, "//button[contains(., 'Check')]"))
        )

        print("Captcha passed successfully!")
        
        final_success_path = f"screenshots/final_success_text_{datetime.now().strftime('%H%M%S')}.png"
        driver.save_screenshot(final_success_path)
        screenshot_paths.append(final_success_path)
        create_success_gif(screenshot_paths, output_folder=f"successful_solves/text_{provider}")
        return 1
    except Exception as e:
        print(f"Captcha failed... Error: {e}")
        return 0

def recaptcha_v2_test(driver, provider='openai', model=None):
    """
    Solves a single reCAPTCHA v2 instance on the 2captcha demo page.
    Returns 1 for success, 0 for failure.
    """
    driver.get("https://2captcha.com/demo/recaptcha-v2")
    
    screenshot_paths = []
    try:
        # --- Start the challenge ---
        recaptcha_frame = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.XPATH, "//iframe[@title='reCAPTCHA']")))
        driver.switch_to.frame(recaptcha_frame)
        WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.CLASS_NAME, "recaptcha-checkbox-border"))).click()
        driver.switch_to.default_content()
        time.sleep(2)

        # --- Loop to solve image challenges as long as they appear ---
        MAX_CHALLENGE_ATTEMPTS = 5
        clicked_tile_indices = set()
        last_object_name = ""
        num_last_clicks = 0
        for attempt in range(MAX_CHALLENGE_ATTEMPTS):
            print(f"\nreCAPTCHA image challenge attempt {attempt + 1}/{MAX_CHALLENGE_ATTEMPTS}...")
            
            # --- Check if a puzzle is present ---
            try:
                challenge_iframe = WebDriverWait(driver, 3).until(EC.presence_of_element_located((By.XPATH, "//iframe[contains(@title, 'recaptcha challenge expires in two minutes')]")))
                driver.switch_to.frame(challenge_iframe)
            except Exception:
                print("No new image challenge found. Proceeding to final submission.")
                break # Exit the loop

            # --- If puzzle is found, solve it ---
            instruction_element = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CLASS_NAME, "rc-imageselect-instructions")))
            instruction_screenshot_path = f'screenshots/recaptcha_instruction_{attempt + 1}.png'
            instruction_element.screenshot(instruction_screenshot_path)
            screenshot_paths.append(instruction_screenshot_path)
            
            object_name = ''
            if provider == 'openai':
                object_name = ask_recaptcha_instructions_to_chatgpt(instruction_screenshot_path, model)
            else: # gemini
                object_name = ask_recaptcha_instructions_to_gemini(instruction_screenshot_path, model)
            print(f"AI identified the target object as: '{object_name}'")

            is_new_object = object_name.lower() != last_object_name.lower()
            if is_new_object:
                print(f"New challenge object detected ('{object_name}'). Resetting clicked tiles.")
                clicked_tile_indices = set()
                last_object_name = object_name
            elif num_last_clicks >= 3:
                print("Previously clicked 3 or more tiles, assuming a new challenge. Resetting clicked tiles.")
                clicked_tile_indices = set()
            else:
                print("Same challenge object and < 3 tiles clicked previously. Will not re-click already selected tiles.")

            table = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.XPATH, "//table[contains(@class, 'rc-imageselect-table')]")))
            all_tiles = table.find_elements(By.TAG_NAME, "td")
            
            tile_paths = []
            for i, tile in enumerate(all_tiles):
                tile_path = f'screenshots/tile_{attempt + 1}_{i}.png'
                tile.screenshot(tile_path)
                screenshot_paths.append(tile_path)
                tile_paths.append(tile_path)

            tasks = [(i, path, object_name, provider, model) for i, path in enumerate(tile_paths)]
            tiles_to_click_this_round = []
            with ThreadPoolExecutor(max_workers=len(all_tiles)) as executor:
                results = executor.map(check_tile_for_object, tasks)
                for tile_index, should_click in results:
                    if should_click:
                        tiles_to_click_this_round.append(tile_index)

            current_attempt_tiles = set(tiles_to_click_this_round)
            new_tiles_to_click = current_attempt_tiles - clicked_tile_indices
            num_last_clicks = len(new_tiles_to_click)

            print(f"\nAI identified tiles for clicking: {sorted(list(current_attempt_tiles))}")
            print(f"Already clicked tiles: {sorted(list(clicked_tile_indices))}")
            print(f"Clicking {len(new_tiles_to_click)} new tiles...")
            
            for i in sorted(list(new_tiles_to_click)):
                try:
                    if all_tiles[i].is_displayed() and all_tiles[i].is_enabled():
                        all_tiles[i].click()
                        time.sleep(random.uniform(0.2, 0.5))
                except Exception as e:
                    print(f"Could not click tile {i}, it might be already selected or disabled. Error: {e}")
            
            clicked_tile_indices.update(new_tiles_to_click)

            try:
                verify_button = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.ID, "recaptcha-verify-button")))
                verify_button.click()
                time.sleep(1.5) # Wait for state change

                # After clicking, check if the button is now disabled, which indicates success
                verify_button_after_click = driver.find_element(By.ID, "recaptcha-verify-button")
                if verify_button_after_click.get_attribute("disabled"):
                    print("Verify button is disabled. Image challenge passed.")
                    driver.switch_to.default_content()
                    print("reCAPTCHA v2 passed successfully!")
        
                    final_success_path = f"screenshots/final_success_recaptcha_v2_{datetime.now().strftime('%H%M%S')}.png"
                    driver.save_screenshot(final_success_path)
                    screenshot_paths.append(final_success_path)
                    
                    create_success_gif(screenshot_paths, output_folder=f"successful_solves/recaptcha_v2_{provider}")
                    return 1
                else:
                    # This case handles "check new images" - we just let the loop continue
                    print("Verify button still active, likely a new challenge was served.")

            except Exception:
                print("Verify button not found after clicking tiles, assuming challenge is complete.")
                break # Exit the loop to the final submission step

            driver.switch_to.default_content()
            time.sleep(2)
        else:
            # This 'else' belongs to the 'for' loop. Runs if the loop completes without a 'break'.
            print("Image challenge still present after max attempts.")
            return 0

        # --- Submit main page form ---
        check_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "button[data-action='demo_action']"))
        )
        check_button.click()

        # Check for the success message using the correct class name
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CLASS_NAME, "_successMessage_1ndnh_1"))
        )

        print("reCAPTCHA v2 passed successfully!")
        
        final_success_path = f"screenshots/final_success_recaptcha_v2_{datetime.now().strftime('%H%M%S')}.png"
        driver.save_screenshot(final_success_path)
        screenshot_paths.append(final_success_path)
        
        create_success_gif(screenshot_paths, output_folder=f"successful_solves/recaptcha_v2_{provider}")
        return 1
    
    except Exception as ex:
        print(f"An error occurred during reCAPTCHA v2 test: {ex}. Marking as failed.")
        traceback.print_exc()
        try:
            driver.switch_to.default_content()
        except Exception:
            pass
        return 0

def main():
    parser = argparse.ArgumentParser(description="Test various captcha types.")
    parser.add_argument('captcha_type', choices=['puzzle', 'text', 'complicated_text', 'recaptcha_v2', 'audio'],
                        help="Specify the type of captcha to test")
    parser.add_argument('--provider', choices=['openai', 'gemini'], default='openai', help="Specify the AI provider to use")
    parser.add_argument('--file', type=str, default='files/audio.mp3', help="Path to the local audio file for the 'audio' test.")
    parser.add_argument('--model', type=str, default=None, help="Specify the AI model to use (e.g., 'gpt-4o', 'gemini-2.5-flash').")
    args = parser.parse_args()

    os.makedirs('screenshots', exist_ok=True)

    if args.captcha_type == 'audio':
        # Audio test is now provider-aware
        audio_test(args.file, args.provider, args.model)
        return

    driver = webdriver.Firefox()
    try:
        if args.captcha_type == 'puzzle':
            solve_geetest_puzzle(driver, args.provider)
        elif args.captcha_type == 'text':
            text_test(driver, args.provider, args.model)
        elif args.captcha_type == 'complicated_text':
            complicated_text_test(driver, args.provider, args.model)
        elif args.captcha_type == 'recaptcha_v2':
            recaptcha_v2_test(driver, args.provider, args.model)
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
