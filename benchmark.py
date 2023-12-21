import time
import requests

prompts = [
    "Generate a list of ten titles for my autobiography. The book is about my journey as an adventurer who has lived an unconventional life, meeting many different personalities and finally finding peace in gardening.",
    "Which party won the 2023 general election in Paraguay?",
    """You are a parser who parses things into a JSON format. Examples:

Format: {"type": "greeting"|"farewell"}
Input: Hi, how is it going?
Result: {"type": "greeting"}

Format: {"name": @string, "age": @number, "interests": [@string]}
Input: Hi, my name is John! I like to take walks on the beach and play ukulele. I am twenty years old, and I am searching for a girlfriend.
Result: {"name": "John", "age": 20, "interests": ["walk on the beach", "play ukulele", "girlfriend"]}

Format: {"type": "inspect"|"take"|"talk", "targets": [@string], "method": string?}
Input: I take a closer look at the shelves and cabinets to see what objects they have.
Result:""",
    "What is the capital of Germany?",
    "Choose a leetcode hard problem, solve it in Kotlin.",
    "Who said \"To be or not to be?\"?"
    "Write simple, concise code that does not rely on any library functions.  The code must start with ```python and end with ```.  Write a python function glork(bork) with input length bork that returns a list with the first `bork` elements of the fibonacci sequence."
]

def call_llama(kai_url, current_payload):
    llama_request = {
        'prompt': prompt,
        'stop': current_payload.get('stop_sequence',[]),
        'n_predict': current_payload.get('max_length', 512),
        'temperature': current_payload.get('temperature', 1.0),
        'tfs_z': current_payload.get('tfs', 1.0),
        'top_k': current_payload.get('top_k', 40),
        'top_p': current_payload.get('top_p', 1.0),
        'repeat_penalty': current_payload.get('rep_pen',1.0),
        'repeat_last_n': current_payload.get('rep_pen_range',64),
        'typical_p': current_payload.get('typical',0.0)
    }
    gen_req = requests.post(kai_url + '/completion', json = llama_request, timeout=300)
    return gen_req.json()

for cycle in range(3):
    all_times = 0
    count = 0
    for idx,prompt in enumerate(prompts):
        base_url = 'http://localhost:8080'
        
        answer = call_llama(base_url, {'prompt': f'[INST]{prompt}[/INST] ' })
        timings = answer['timings']
        
        predicted_ms = timings['predicted_ms']
        predicted_per_second = timings['predicted_per_second']
        prompt_ms = timings['prompt_ms']
        prompt_per_second = timings['prompt_per_second']        
                    
        print(f"{idx} done in {predicted_ms+prompt_ms}ms, {predicted_per_second:.2f} tok/sec")
        
        all_times += predicted_ms+prompt_ms
        count += 1
        
    print(f"-- {cycle} done, average {all_times/count}ms")
        