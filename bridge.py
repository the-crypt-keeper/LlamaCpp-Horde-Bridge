import requests, json, os, time, argparse, urllib3
from logger import logger, set_logger_verbosity, quiesce_logger, test_logger

import random
import time

try:
    import clientData as cd
except:
    class temp(object):
        def __init__(self):
            random.seed()
            # The cluster url
            self.cluster_url = "https://stablehorde.net"
            # Where can your bridge reach your KAI instance
            self.kai_url = "http://localhost:5000"
            # Give a cool name to your instance
            self.kai_name = f"Automated Instance #{random.randint(-100000000, 100000000)}"
            # The api_key identifies a unique user in the horde
            # Visit https://koboldai.net/register to create one before you can join
            self.api_key = "0000000000"
            # Put other users whose prompts you want to prioritize.
            # The owner's username is always included so you don't need to add it here, unless you want it to have lower priority than another user
            self.priority_usernames = []
    cd = temp()
    pass


class kai_bridge():
    def __init__(self):
        self.model = ''
        self.max_context_length = 1024
        self.max_length = 80
        self.current_softprompt = None
        self.softprompts = {}
        self.run = True
        self.last_retrieved = None
            
    def stop(self):
        self.run = False
    
    @logger.catch
    def validate_kai(self, kai):
        if self.model != '' and (self.last_retrieved is None or time.time() - self.last_retrieved <= 30):
            return True
        self.last_retrieved = time.time()
        logger.debug("Retrieving settings from LamaCpp Server...")
        try:
            req = requests.get(kai + '/model.json')
            gen_settings = req.json()
            
            self.model = 'koboldcpp/'+os.path.basename(gen_settings["model"]).replace('.gguf','')          
            self.max_context_length = int(gen_settings["n_ctx"])
            self.max_length = int(self.max_context_length/2)
            self.softprompts[self.model] = []
            self.current_softprompt = ""
            logger.info(f"llama.cpp server model={self.model} n_ctx={self.max_context_length}")
        except requests.exceptions.JSONDecodeError:
            logger.error(f"Server {kai} is up but does not appear to be a KoboldAI server. Are you sure it's running the UNITED branch?")
            return(False)
        except requests.exceptions.ConnectionError:
            logger.error(f"Server {kai} is not reachable. Are you sure it's running?")
            return(False)
        return(True)


    def bridge(self, 
        interval, 
        api_key, 
        kai_name, 
        kai_url, 
        horde_url, 
        priority_usernames,
    ):
        current_id = None
        current_payload = None
        return_error = None
        loop_retry = 0
        failed_requests_in_a_row = 0
        self.BRIDGE_AGENT = f"LlamaCpp Bridge:10:https://github.com/the-crypt-keeper/LlamaCpp-Horde-Bridge"
        cluster = horde_url
        while self.run:
            headers = {"apikey": api_key}
            if loop_retry > 3 and current_id:
                logger.error(f"Exceeded retry count {loop_retry} for generation id {current_id}. Aborting generation!")
                current_id = None
                current_payload = None
                current_generation = None
                return_error = None
                loop_retry = 0
                submit_dict = {
                    "id": current_id,
                    "state": "faulted",
                    "generation": "faulted",
                    "seed": -1,
                }
                submit_req = requests.post(cluster + '/api/v2/generate/text/submit', json = submit_dict, headers = headers)
                if submit_req.status_code == 404:
                    logger.warning(f"The generation we were working on got stale. Aborting!")
                failed_requests_in_a_row += 1
                if failed_requests_in_a_row > 3:
                    logger.error(f"{failed_requests_in_a_row} Requests failed in a row. Crashing bridge!")
                    return
            elif current_id:
                logger.debug(f"Retrying ({loop_retry}/10) for generation id {current_id}...")
            if not self.validate_kai(kai_url):
                logger.warning(f"Waiting 10 seconds...")
                time.sleep(10)
                continue
            gen_dict = {
                "name": kai_name,
                "models": [self.model],
                "max_length": self.max_length,
                "max_context_length": self.max_context_length,
                "priority_usernames": priority_usernames,
                "softprompts": self.softprompts[self.model],
                "bridge_agent": self.BRIDGE_AGENT,
            }
            # print('gen_dict', gen_dict)
            if current_id:
                loop_retry += 1
            else:
                try:
                    pop_req = requests.post(cluster + '/api/v2/generate/text/pop', json = gen_dict, headers = headers, timeout=40)
                except (urllib3.exceptions.MaxRetryError, requests.exceptions.ConnectionError, requests.exceptions.ReadTimeout):
                    logger.error(f"Server {cluster} unavailable during pop. Waiting 10 seconds...")
                    time.sleep(10)
                    continue
                except requests.exceptions.JSONDecodeError():
                    logger.warning(f"Server {cluster} unavailable during pop. Waiting 10 seconds...")
                    time.sleep(10)
                    continue
                if not pop_req.ok:
                    logger.warning(f"During gen pop, server {cluster} responded: {pop_req.text}. Waiting for 10 seconds...")
                    time.sleep(10)
                    continue
                pop = pop_req.json()
                if not pop:
                    logger.error(f"Something has gone wrong with {cluster}. Please inform its administrator!")
                    time.sleep(interval)
                    continue
                if not pop["id"]:
                    logger.debug(f"Server {cluster} has no valid generations to do for us. Skipped Info: {pop['skipped']}.")
                    time.sleep(interval)
                    continue
                current_id = pop['id']
                current_payload = pop['payload']
                if 'width' in current_payload or 'length' in current_payload or 'steps' in current_payload:
                    logger.warning(f"Stable Horde payload detected: {current_payload}. Aborting ")
                    current_id = None
                    current_payload = None
                    current_generation = None
                    return_error = None
                    loop_retry = 0
                    continue
                # By default, we don't want to be annoucing the prompt send from the Horde to the terminal
                current_payload['quiet'] = True
                requested_softprompt = pop['softprompt']
            logger.info(f"Job received from {cluster} for {current_payload.setdefault('max_length',80)} tokens and {current_payload.setdefault('max_context_length',1024)} max context. Starting generation...")
            
            # if "soft_prompt" in current_payload and current_payload["soft_prompt"] not in self.softprompts[self.model]:
            #     #prevent unknown rogue softprompt from crashing horde worker
            #     current_payload["soft_prompt"] = "" #this is a valid value that functions like no softprompt
            
            # if requested_softprompt != self.current_softprompt:
            #     req = requests.put(kai_url + '/api/latest/config/soft_prompt/', json = {"value": requested_softprompt})
            #     time.sleep(1) # Wait a second to unload the softprompt
                
            try:
                llama_request = {
                    'prompt': current_payload['prompt'],
                    'stop': current_payload.get('stop_sequence',[]),
                    'n_predict': current_payload['max_length'],
                    'temperature': current_payload['temperature'],
                    'tfs_z': current_payload['tfs'],
                    'top_k': current_payload['top_k'],
                    'top_p': current_payload['top_p'],
                    'repeat_penalty': current_payload['rep_pen'],
                    'repeat_last_n': current_payload['rep_pen_range'],
                    'typical_p': current_payload['typical']
                }
                # print('original:', current_payload)
                # print('llama:', llama_request)
                gen_req = requests.post(kai_url + '/completion', json = llama_request, timeout=300)
            except (requests.exceptions.ConnectionError, requests.exceptions.ReadTimeout):
                logger.error(f"Worker {kai_url} unavailable. Waiting 10 seconds...")
                loop_retry += 1
                time.sleep(10)
                continue
            if type(gen_req.json()) is not dict:
                logger.error(f'KAI instance {kai_url} API unexpected response on generate: {gen_req}. Sleeping 10 seconds...')
                time.sleep(9)
                loop_retry += 1
                continue
            if gen_req.status_code == 503:
                logger.debug(f'KAI instance {kai_url} Busy (attempt {loop_retry}). Will try again...')
                loop_retry += 1
                continue
            if gen_req.status_code == 422:
                logger.debug(f'KAI instance {kai_url} reported validation error. Returning as error.')
                return_error = "payload validation error"
            if return_error:
                submit_dict = {
                    "id": current_id,
                    "generation": return_error,
                }
            else:
                try:
                    req_json = gen_req.json()
                except json.decoder.JSONDecodeError:
                    logger.error(f"Something went wrong when trying to generate on {kai_url}. Please check the health of the KAI worker. Retrying 10 seconds...")
                    loop_retry += 1
                    time.sleep(interval)
                    continue
                try:
                    current_generation = req_json["content"]
                except KeyError:
                    logger.error(f"Unexpected response received from {kai_url}: {req_json}. Please check the health of the KAI worker. Retrying in 10 seconds...")
                    logger.debug(current_payload)
                    loop_retry += 1
                    time.sleep(interval)
                    continue
                submit_dict = {
                    "id": current_id,
                    "generation": current_generation,
                }
            while current_id and current_generation:
                try:
                    submit_req = requests.post(cluster + '/api/v2/generate/text/submit', json = submit_dict, headers = headers, timeout=40)
                    if submit_req.status_code == 404:
                        logger.warning(f"The generation we were working on got stale. Aborting!")
                    elif not submit_req.ok:
                        if "already submitted" in submit_req.text:
                            logger.warning(f'Server think this gen already submitted. Continuing')
                        else:
                            logger.error(submit_req.status_code)
                            logger.warning(f"During gen submit, server {cluster} responded: {submit_req.text}. Waiting for 10 seconds...")
                            loop_retry += 1
                            time.sleep(10)
                            continue
                    else:
                        logger.info(f'Submitted generation to {cluster} with id {current_id} and contributed for {submit_req.json()["reward"]}')
                        failed_requests_in_a_row = 0
                    current_id = None
                    current_payload = None
                    current_generation = None
                    return_error = None
                    loop_retry = 0
                except (urllib3.exceptions.MaxRetryError, requests.exceptions.ConnectionError, requests.exceptions.ReadTimeout):
                    logger.warning(f"Server {cluster} unavailable during submit. Waiting 10 seconds...")
                    loop_retry += 1
                    time.sleep(10)
                    continue
            time.sleep(interval)


if __name__ == "__main__":
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument('-i', '--interval', action="store", required=False, type=int, default=2, help="The amount of seconds with which to check if there's new prompts to generate")
    arg_parser.add_argument('-a', '--api_key', action="store", required=False, type=str, help="The API key corresponding to the owner of the KAI instance")
    arg_parser.add_argument('-n', '--kai_name', action="store", required=False, type=str, help="The server name. It will be shown to the world and there can be only one.")
    arg_parser.add_argument('-k', '--kai_url', action="store", required=False, type=str, help="The KoboldAI server URL. Where the bridge will get its generations from.")
    arg_parser.add_argument('-c', '--cluster_url', action="store", required=False, type=str, help="The KoboldAI Cluster URL. Where the bridge will pickup prompts and send the finished generations.")
    arg_parser.add_argument('--debug', action="store_true", default=False, help="Show debugging messages.")
    arg_parser.add_argument('--priority_usernames',type=str, action='append', required=False, help="Usernames which get priority use in this server. The owner's username is always in this list.")
    arg_parser.add_argument('-v', '--verbosity', action='count', default=0, help="The default logging level is ERROR or higher. This value increases the amount of logging seen in your screen")
    arg_parser.add_argument('-q', '--quiet', action='count', default=0, help="The default logging level is ERROR or higher. This value decreases the amount of logging seen in your screen")
    arg_parser.add_argument('--log_file', action='store_true', default=False, help="If specified will dump the log to the specified file")
    args = arg_parser.parse_args()
    set_logger_verbosity(args.verbosity)
    if args.log_file:
        logger.add("llamacpp_bridge_log.log", retention="7 days", level="warning")    # Automatically rotate too big file
    quiesce_logger(args.quiet)
    # test_logger()
    api_key = args.api_key if args.api_key else cd.api_key
    kai_name = args.kai_name if args.kai_name else cd.kai_name
    kai_url = args.kai_url if args.kai_url else cd.kai_url
    horde_url = args.cluster_url if args.cluster_url else cd.cluster_url
    priority_usernames = args.priority_usernames if args.priority_usernames else cd.priority_usernames
    logger.init(f"{kai_name} Instance", status="Started")
    try:
        kai_bridge().bridge(
            interval = args.interval, 
            api_key = api_key, 
            kai_name= kai_name,
            kai_url = kai_url, 
            horde_url = horde_url, 
            priority_usernames=priority_usernames,
        )
    except KeyboardInterrupt:
        logger.info(f"Keyboard Interrupt Received. Ending Process")
    logger.init(f"{kai_name} Instance", status="Stopped")
