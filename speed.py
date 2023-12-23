import sys
import re
import pandas as pd
import datetime
import time

# Initialize an empty dataframe
df = None

# Regular expression patterns
prompt_pattern = re.compile(r'print_timings: prompt eval time =\s+(\d+\.\d+) ms /\s+(\d+) tokens')
eval_pattern = re.compile(r'print_timings:\s+eval time =\s+(\d+\.\d+) ms /\s+(\d+) runs')
total_pattern = re.compile(r'print_timings:\s+total time =\s+(\d+\.\d+) ms')

# Start time for the minute report
start_time = time.time()

# Variables to store intermediate results
prompt_time, prompt_n, eval_time, eval_n = None, None, None, 0

while True:
    line = sys.stdin.readline()
    if not line:
        break

    # Match patterns
    prompt_match = prompt_pattern.search(line)
    eval_match = eval_pattern.search(line)
    total_match = total_pattern.search(line)

    if prompt_match:
        prompt_time, prompt_n = map(float, prompt_match.groups())
    elif eval_match:
        eval_time, eval_n = map(float, eval_match.groups())
        if eval_n == 0: eval_time = 0
    elif total_match and prompt_time and eval_time:
        total_time = float(total_match.group(1))

        # Append to dataframe
        data = pd.DataFrame({
            'timestamp': [datetime.datetime.now()],
            'prompt_n': [prompt_n],
            'eval_n': [eval_n],
            'prompt_time': [prompt_time],
            'eval_time': [eval_time],
            'total_time': [total_time]
        })
        df = data if df is None else pd.concat([df, data], ignore_index=True)

        # Compute and output the effective tokens per second for the current sample
        effective_tokens_per_sec = 1000.0 * eval_n / total_time
        print(f'Effective tokens/sec for current sample: {effective_tokens_per_sec:.1f}')

        # Reset intermediate results
        prompt_time, prompt_n, eval_time, eval_n = None, None, None, 0

    # Report every minute
    if time.time() - start_time >= 60:
        # Filter data from the last minute
        last_minute_data = df[df['timestamp'] >= datetime.datetime.now() - datetime.timedelta(minutes=1)]

        # Calculate statistics
        num_jobs = len(last_minute_data)
        if num_jobs > 0:
            total_prompt_n = last_minute_data['prompt_n'].sum()
            avg_prompt_tokens_per_sec = 1000.0 * total_prompt_n / last_minute_data['prompt_time'].sum()
            total_eval_n = last_minute_data['eval_n'].sum()
            avg_eval_tokens_per_sec = 1000.0 * total_eval_n / last_minute_data['eval_time'].sum()
            effective_avg_tokens_per_sec = 1000.0 * total_eval_n / last_minute_data['total_time'].sum()
            efficiency = 100.0 * last_minute_data['total_time'].sum() / 60000

            # Print report
            print(f'  Last minute: {num_jobs} jobs, {efficiency:.1f}% efficient')
            print(f'  Total number of prompt tokens: {total_prompt_n:.0f}, average {avg_prompt_tokens_per_sec:.1f} tokens/sec.')
            print(f'  Total number of eval tokens: {total_eval_n:.0f}, average {avg_eval_tokens_per_sec:.1f} tokens/sec.')
            print(f'  Overall effective rate: {effective_avg_tokens_per_sec:.1f} tokens/sec')
        else:
            print('  No jobs in the last minute.')

        # Reset start time
        start_time = time.time()