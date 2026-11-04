import time
import subprocess
import sys
from pathlib import Path
from datetime import datetime

# ==========================================================
# CONFIGURATION
# ==========================================================
# How often should the AI retrain? 
# 12 hours = 43,200 seconds
WAIT_TIME_SECONDS = 6 * 60 * 60

print("🤖 Automated AI Training Service Started!")
print("This script will silently update your AI model in the background.")
print("="*60)

while True:
    try:
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n[{current_time}] 🚀 Initiating Automated AI Retraining...")
        
        # This command runs your train_model.py script exactly as if you typed it in the terminal
        result = subprocess.run(["python", "train_model.py"], capture_output=True, text=True)
        
        over_result = subprocess.run([sys.executable, str(Path(__file__).with_name("train_model_over15.py"))], capture_output=True, text=True)
        print(over_result.stdout if over_result.returncode == 0 else over_result.stderr)

        # Check if the training was successful
        if result.returncode == 0:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ AI Retraining Complete. 'ai_brain.pkl' successfully updated!")
            # Optional: Print the last few lines of the training output so you can see the new accuracy!
            output_lines = result.stdout.strip().split('\n')
            for line in output_lines[-5:]:
                if "ACCURACY" in line:
                    print(f"📈 {line.strip()}")
        else:
            print(f"⚠️ Training failed. Error log:\n{result.stderr}")
            
    except Exception as e:
        print(f"🔴 Critical Error in Auto-Trainer: {e}")

    # Go to sleep until the next cycle
    print(f"💤 Going to sleep. The AI will study new data again in {WAIT_TIME_SECONDS / 3600} hours.")
    time.sleep(WAIT_TIME_SECONDS)