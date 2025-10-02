import os
import time
import random
import math
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from PIL import Image, ImageDraw, ImageFont
from selenium.webdriver.common.action_chains import ActionChains
from ai_utils import (
    ask_puzzle_distance_to_gemini, 
    ask_puzzle_correction_direction_to_gemini, 
    ask_best_fit_to_gemini,
    ask_puzzle_distance_to_chatgpt,
    ask_puzzle_correction_direction_to_openai,
    ask_best_fit_to_openai
)
import traceback

def geometric_progression_steps(initial_value, threshold=0.5):
    """Calculates a series of steps that decrease geometrically."""
    if initial_value <= 0: return []
    steps = []
    current_value = initial_value
    while current_value > threshold:
        step = current_value * 0.5 
        steps.append(step)
        current_value -= step
    if current_value > 0:
        steps.append(current_value)
    return steps

def perform_final_drag(driver, offset):
    """Performs a multi-stage human-like drag to avoid bot detection."""
    slider = WebDriverWait(driver, 10).until(
        EC.element_to_be_clickable((By.CLASS_NAME, "geetest_slider_button"))
    )

    sleep_time = random.uniform(0.3, 0.4)
    
    # Break the move into three distinct parts
    part1 = offset * random.uniform(0.70, 0.80)
    part2 = offset * random.uniform(0.15, 0.25)
    part3 = offset - part1 - part2

    actions = ActionChains(driver)
    
    # Perform the sequence with pauses between stages
    actions.click_and_hold(slider).perform()
    time.sleep(sleep_time) # 1. Pause after grab

    # 2. Part 1: Fast initial slide
    actions.move_by_offset(part1, 0).perform()
    time.sleep(sleep_time) # Short pause after first movement

    # 3. Part 2: Slower aiming slide
    actions.move_by_offset(part2, 0).perform()
    time.sleep(sleep_time) # Longer pause for final aim

    # 4. Part 3: Final placement
    actions.move_by_offset(part3, 0).perform()
    time.sleep(sleep_time) # Pause before release
    
    actions.release().perform()

def create_success_gif(image_paths, output_folder="successful_solves"):
    """Creates a GIF from a list of images and saves it."""
    if not image_paths:
        print("No images provided for GIF creation.")
        return

    os.makedirs(output_folder, exist_ok=True)
    
    valid_images = []
    for path in image_paths:
        if os.path.exists(path):
            try:
                # Convert to RGB to prevent mode issues (e.g., RGBA vs RGB) and open
                valid_images.append(Image.open(path).convert("RGB"))
            except Exception as e:
                print(f"Warning: Could not open or convert image {path}. Skipping. Error: {e}")
        else:
            print(f"Warning: Image path for GIF not found: {path}. Skipping.")

    if not valid_images:
        print("\nCould not create success GIF because no valid source images were found.")
        return

    try:
        # Resize all images to match the first one for consistency
        base_size = valid_images[0].size
        resized_images = [img.resize(base_size) for img in valid_images]

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = os.path.join(output_folder, f"success_{timestamp}.gif")

        resized_images[0].save(
            output_path,
            save_all=True,
            append_images=resized_images[1:],
            duration=800,  # Milliseconds per frame
            loop=0  # Loop forever
        )
        print(f"\n✨ Successfully saved solution GIF to {output_path}")
    except Exception as e:
        print(f"\nCould not create success GIF. Error: {e}")

def set_slider_position_for_screenshot(driver, offset):
    """Uses JavaScript to instantly set the slider's visual position for an accurate screenshot."""
    slider_knob = driver.find_element(By.CLASS_NAME, "geetest_slider_button")
    puzzle_piece = driver.find_element(By.CLASS_NAME, "geetest_canvas_slice")
    
    # Use JavaScript to directly set the CSS transform property
    driver.execute_script(
        f"arguments[0].style.transform = 'translateX({offset}px)'; arguments[1].style.transform = 'translateX({offset}px)';",
        slider_knob,
        puzzle_piece
    )

def solve_geetest_puzzle(driver, provider='gemini'):
    """
    Solves a single Geetest puzzle instance using the specified AI provider,
    with up to 3 attempts on new puzzles if it fails.
    Returns 1 for success, 0 for failure.
    """
    if not os.path.exists('screenshots'):
        os.makedirs('screenshots')
    
    generated_files = []
    try:
        driver.get("https://2captcha.com/demo/geetest")
        
        print("Automatically clicking button to start puzzle challenge...")
        try:
            start_button = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.CLASS_NAME, "geetest_radar_tip")))
            start_button.click()
        except Exception as e:
            print(f"Could not start puzzle. Maybe it's already active? Error: {e}")


        for attempt in range(3):
            print(f"\n--- Puzzle Attempt {attempt + 1}/3 ---")
            try:
                # Per your request, waiting a fixed 3 seconds for the puzzle to fully render.
                print("Waiting 3 seconds for puzzle to render...")
                time.sleep(3)

                screenshot_element = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CLASS_NAME, "geetest_window")))
                
                initial_screenshot_path = f'screenshots/initial_puzzle_attempt_{attempt + 1}.png'
                screenshot_element.screenshot(initial_screenshot_path)
                generated_files.append(initial_screenshot_path)
                print(f"Saved initial puzzle state to {initial_screenshot_path}")

                # --- Step 1: Get initial pixel guess from AI ---
                print(f"\n--- Step 1: Asking {provider.upper()} for initial slide distance ---")
                initial_offset_str = ""
                if provider == 'openai':
                    initial_offset_str = ask_puzzle_distance_to_chatgpt(initial_screenshot_path)
                else: # gemini
                    initial_offset_str = ask_puzzle_distance_to_gemini(initial_screenshot_path)

                print(f"Raw AI response for initial distance: '{initial_offset_str}'")

                if initial_offset_str is None:
                    print("AI failed to provide a valid initial distance. Refreshing puzzle...")
                    if attempt < 2:
                        refresh_button = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.CLASS_NAME, "geetest_refresh_1")))
                        refresh_button.click()
                    continue # Move to the next attempt

                try:
                    initial_offset_raw = int(''.join(filter(str.isdigit, initial_offset_str)))
                    print(f"AI suggests a raw offset of {initial_offset_raw}px.")

                    scaling_factor = 1.0 # Default scaling
                    if provider == 'gemini':
                        scaling_factor = 0.791
                    
                    initial_offset = int(initial_offset_raw * scaling_factor)
                    print(f"Applying scaling factor ({scaling_factor}). New offset is {initial_offset}px.")

                except (ValueError, TypeError):
                    print(f"Could not parse a valid integer from AI response: '{initial_offset_str}'. Skipping attempt.")
                    # Refresh for the next attempt
                    if attempt < 2:
                        refresh_button = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.CLASS_NAME, "geetest_refresh_1")))
                        refresh_button.click()
                        print("Refreshing puzzle for next attempt...")
                    continue
                
                print(f"Performing initial human-like slide to {initial_offset}px...")
                perform_final_drag(driver, initial_offset)
                
                correction_screenshot_path = f'screenshots/correction_needed_attempt_{attempt + 1}.png'
                screenshot_element.screenshot(correction_screenshot_path)
                generated_files.append(correction_screenshot_path)
                print(f"Saved state for correction analysis to {correction_screenshot_path}")

                success = False
                for _ in range(6):
                    try:
                        success_element = driver.find_element(By.CLASS_NAME, "geetest_success_radar_tip_content")
                        if "Verification Success" in success_element.text:
                            success = True
                            break
                    except Exception:
                        pass
                    time.sleep(0.5)

                if success:
                    print("\n✅ Puzzle solved successfully on the first slide!")
                    final_success_path = f"screenshots/final_success_{datetime.now().strftime('%H%M%S')}.png"
                    driver.save_screenshot(final_success_path)
                    generated_files.append(final_success_path)
                    create_success_gif([initial_screenshot_path, correction_screenshot_path, final_success_path])
                    return 1

                print("First slide failed. Proceeding to fine-grained scan...")

                # --- Step 2: Get correction direction and perform scan ---
                direction = 0
                if initial_offset < 50:
                    direction = 1
                elif initial_offset > 250:
                    direction = -1
                else:
                    direction_str = ""
                    if provider == 'openai':
                        direction_str = ask_puzzle_correction_direction_to_openai(correction_screenshot_path)
                    else:
                        direction_str = ask_puzzle_correction_direction_to_gemini(correction_screenshot_path)
                    direction = 1 if '+' in direction_str else -1
                
                scan_step = 5
                num_scans = 3
                scan_screenshots = []
                
                slider = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.CLASS_NAME, "geetest_slider_button")))
                action = ActionChains(driver)
                action.click_and_hold(slider).perform()
                time.sleep(0.1)

                try:
                    for i in range(num_scans):
                        current_pos = initial_offset + (i * scan_step * direction)
                        if current_pos < 0: continue
                        set_slider_position_for_screenshot(driver, current_pos)
                        time.sleep(0.05)
                        screenshot_path = f'screenshots/scan_attempt_{attempt + 1}_{i}_{current_pos}px.png'
                        screenshot_element.screenshot(screenshot_path)
                        scan_screenshots.append(screenshot_path)
                        generated_files.append(screenshot_path)
                finally:
                    set_slider_position_for_screenshot(driver, 0)
                    time.sleep(0.1)
                    action.release().perform()
                time.sleep(1)

                if not scan_screenshots:
                    print("No scan screenshots were taken. Refreshing for next attempt.")
                    if attempt < 2:
                        refresh_button = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.CLASS_NAME, "geetest_refresh_1")))
                        refresh_button.click()
                    continue

                # --- Step 3: Ask AI to pick the best fit and submit ---
                best_fit_index_str = ""
                if provider == 'openai':
                    best_fit_index_str = ask_best_fit_to_openai(scan_screenshots)
                else:
                    best_fit_index_str = ask_best_fit_to_gemini(scan_screenshots)
                
                print(f"Raw AI response for best fit: '{best_fit_index_str}'")

                if best_fit_index_str is None:
                    print("AI failed to provide a valid best-fit index. Refreshing puzzle...")
                    if attempt < 2:
                        refresh_button = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.CLASS_NAME, "geetest_refresh_1")))
                        refresh_button.click()
                    continue # Move to the next attempt

                try:
                    best_fit_index = int(best_fit_index_str)
                    if not (0 <= best_fit_index < len(scan_screenshots)):
                        raise ValueError("Index out of bounds.")
                except (ValueError, TypeError):
                    print(f"Could not parse a valid index from AI response: '{best_fit_index_str}'. Refreshing.")
                    if attempt < 2:
                        refresh_button = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.CLASS_NAME, "geetest_refresh_1")))
                        refresh_button.click()
                    continue
                    
                final_offset = initial_offset + (best_fit_index * scan_step * direction)
                print(f"AI chose image index {best_fit_index}. Calculated final offset: {final_offset}px. Submitting...")
                perform_final_drag(driver, final_offset)
                
                success_final = False
                for _ in range(6):
                    try:
                        success_element = driver.find_element(By.CLASS_NAME, "geetest_success_radar_tip_content")
                        if "Verification Success" in success_element.text:
                            success_final = True
                            break
                    except Exception:
                        pass
                    time.sleep(0.5)
                
                if success_final:
                    print(f"\n✅ Puzzle solved successfully on Attempt #{attempt + 1}!")
                    final_success_path = f"screenshots/final_success_{datetime.now().strftime('%H%M%S')}.png"
                    driver.save_screenshot(final_success_path)
                    generated_files.append(final_success_path)
                    create_success_gif([initial_screenshot_path, correction_screenshot_path, scan_screenshots[best_fit_index], final_success_path], output_folder=f"successful_solves/puzzle_{provider}")
                    return 1
                else:
                    print(f"\n❌ Attempt {attempt + 1} failed.")
                    if attempt < 2:
                        refresh_button = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.CLASS_NAME, "geetest_refresh_1")))
                        refresh_button.click()
                        print("Refreshing puzzle for next attempt...")

            except Exception as e:
                print(f"An unexpected error occurred during attempt {attempt + 1}: {e}")
                traceback.print_exc()
                if attempt < 2:
                    try:
                        refresh_button = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.CLASS_NAME, "geetest_refresh_1")))
                        refresh_button.click()
                        print("Refreshing puzzle due to error...")
                    except Exception as refresh_e:
                        print(f"Could not refresh puzzle after error: {refresh_e}")
                        return 0 # Cannot recover, exit
                
        print("\nAll 3 puzzle attempts failed.")
        return 0
    finally:
        print("\nCleaning up generated puzzle files...")
        for f in generated_files:
            try:
                os.remove(f)
                print(f"  Deleted {f}")
            except OSError as e:
                print(f"  Error deleting file {f}: {e}")

def main():
    driver = webdriver.Firefox()
    try:
        # Example: run with solve_geetest_puzzle(driver, provider='openai')
        solve_geetest_puzzle(driver, provider='gemini')
    finally:
        print("Closing browser in 5 seconds...")
        time.sleep(5)
        driver.quit()

if __name__ == "__main__":
    main() 