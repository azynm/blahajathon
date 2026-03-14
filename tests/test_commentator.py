import os
import sys

# Add parent directory to path so we can import frontend modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from commentator.commentator import generate_commentary_audio
from commentator.mock_data import ALL_SCENARIOS

def test_all_scenarios():
    print("=== Testing All MOCK DATA Scenarios ===")
    for scenario_name, events in ALL_SCENARIOS.items():
        print(f"\n--- Running {scenario_name} ---")
        try:
            audio_data = generate_commentary_audio(events)
            
            if audio_data:
                filename = f"test_{scenario_name.lower().replace(' ', '_').replace(':', '')}.mp3"
                with open(filename, "wb") as f:
                    f.write(audio_data)
                print(f"Success! Saved output to {filename}\n")
            else:
                print(f"Failed to generate audio for {scenario_name}.\n")
        except Exception as e:
            print(f"Error testing {scenario_name}: {e}")

if __name__ == "__main__":
    test_all_scenarios()
