import requests, json, os, time, argparse, urllib3, threading, queue, random, time
from logger import logger, set_logger_verbosity, quiesce_logger, test_logger

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
        self.run = True
        self.last_retrieved = None

        self.submit_queue = queue.Queue()
        self.failed_requests_in_a_row = 0
        self.failed_requests_lock = threading.Lock()
        
        self.submit_thread = None
                    
    def stop(self):
        self.run = False
        if self.submit_thread is not None:
            self.submit_queue.put(None)
            self.submit_thread.join()
        
    def submit_generation(self, horde_url, api_key):
        headers = {"apikey": api_key}
        cluster = horde_url
        
        while self.run:
            submit_dict = self.submit_queue.get()
            if submit_dict is None: continue
            while True:
                try:
                    submit_req = requests.post(cluster + '/api/v2/generate/text/submit', json = submit_dict, headers = headers, timeout=40)
                    if submit_req.status_code == 404:
                        logger.warning(f"The generation we were working on got stale. Aborting.")
                        break
                    elif not submit_req.ok:
                        if "already submitted" in submit_req.text:
                            logger.warning(f'Server think this gen already submitted. Aborting.')
                            break
                        else:
                            logger.error(submit_req.status_code)
                            logger.warning(f"During gen submit, server {cluster} responded: {submit_req.text}. Waiting for 10 seconds...")
                            time.sleep(10)
                            continue
                    else:
                        logger.info(f'Submitted generation to {cluster} with id {submit_dict.get("id")} and contributed for {submit_req.json()["reward"]}')
                        with self.failed_requests_lock:
                            self.failed_requests_in_a_row = 0
                        break
                except (urllib3.exceptions.MaxRetryError, requests.exceptions.ConnectionError, requests.exceptions.ReadTimeout):
                    logger.warning(f"Server {cluster} unavailable during submit. Waiting 10 seconds...")
                    time.sleep(10)
                    continue
            self.submit_queue.task_done()
                
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

            logger.info(f"llama.cpp server model={self.model} n_ctx={self.max_context_length}")
        except requests.exceptions.JSONDecodeError:
            logger.error(f"Server {kai} is up but does not appear to be a LamaCpp server.")
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

        self.BRIDGE_AGENT = f"LlamaCpp Bridge:11:https://github.com/the-crypt-keeper/LlamaCpp-Horde-Bridge"
        cluster = horde_url
        headers = {"apikey": api_key}
        
        self.submit_thread = threading.Thread(target=self.submit_generation, args=(horde_url, api_key))
        self.submit_thread.start()
        
        while self.run:
            
            # Generation error handling logic
            if loop_retry > 3 and current_id:
                logger.error(f"Exceeded retry count {loop_retry} for generation id {current_id}. Aborting generation!")

                submit_dict = {
                    "id": current_id,
                    "state": "faulted",
                    "generation": "faulted",
                    "seed": -1,
                }
                submit_req = requests.post(cluster + '/api/v2/generate/text/submit', json = submit_dict, headers = headers)
                
                current_id = None
                current_payload = None
                current_generation = None
                return_error = None
                loop_retry = 0
                                
                if submit_req.status_code == 404:
                    logger.warning(f"The generation we were working on got stale. Aborting!")
                with self.failed_requests_lock:
                    self.failed_requests_in_a_row += 1
                    failed_requests_in_a_row_copy = self.failed_requests_in_a_row
                if failed_requests_in_a_row_copy > 3:
                    logger.error(f"{failed_requests_in_a_row_copy} Requests failed in a row. Crashing bridge!")
                    return
            
            # Fetch model info from server
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
                "softprompts": [],
                "bridge_agent": self.BRIDGE_AGENT,
            }
            
            # Pop a new text generation job?
            if current_id:
                logger.warning(f"Retrying ({loop_retry}/10) for generation id {current_id}...")
            else:
                # Request
                try:
                    pop_req = requests.post(cluster + '/api/v2/generate/text/pop', json = gen_dict, headers = headers, timeout=40)
                except (urllib3.exceptions.MaxRetryError, requests.exceptions.ConnectionError, requests.exceptions.ReadTimeout, requests.exceptions.JSONDecodeError):
                    logger.error(f"Server {cluster} unavailable during pop. Waiting 10 seconds...")
                    time.sleep(10)
                    continue

                # Validate
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

                # Make sure it's not an image job
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

                logger.info(f"New job received from {cluster} for {current_payload.setdefault('max_length',80)} tokens and {current_payload.setdefault('max_context_length',1024)} max context. Starting generation...")

            # Perform generation
            try:
                llama_request = {
                    'prompt': current_payload['prompt'],
                    'stop': current_payload.get('stop_sequence',[]),
                    'n_predict': current_payload['max_length'],
                    'temperature': current_payload.get('temperature',1.0),
                    'tfs_z': current_payload.get('tfs',1.0),
                    'top_k': current_payload.get('top_k',0),
                    'top_p': current_payload.get('top_p',1.0),
                    'repeat_penalty': current_payload.get('rep_pen',1.0),
                    'repeat_last_n': current_payload.get('rep_pen_range',64),
                    'typical_p': current_payload.get('typical',0.0)
                }
                gen_req = requests.post(kai_url + '/completion', json = llama_request, timeout=300)
            except (requests.exceptions.ConnectionError, requests.exceptions.ReadTimeout):
                logger.error(f"Worker {kai_url} unavailable. Waiting 10 seconds...")
                loop_retry += 1
                time.sleep(10)
                continue
            
            # Validate generation
            if gen_req.status_code == 503:
                logger.debug(f'LamaCpp instance {kai_url} Busy (attempt {loop_retry}). Will try again...')
                loop_retry += 1
                continue
            if gen_req.status_code == 422:
                logger.debug(f'LamaCpp instance {kai_url} reported validation error. Returning as error.')
                return_error = "payload validation error"
            if return_error:
                submit_dict = {
                    "id": current_id,
                    "generation": return_error,
                }
            else:
                try:
                    req_json = gen_req.json()
                except requests.exceptions.JSONDecodeError:
                    logger.error(f"Something went wrong when trying to generate on {kai_url}. Please check the health of the LamaCpp server. Retrying 10 seconds...")
                    loop_retry += 1
                    time.sleep(interval)
                    continue
                try:
                    current_generation = req_json["content"]
                    logger.info(json.dumps(req_json["timings"]))
                except KeyError:
                    logger.error(f"Unexpected response received from {kai_url}: {req_json}. Please check the health of the LamaCpp server. Retrying in 10 seconds...")
                    logger.debug(llama_request)
                    loop_retry += 1
                    time.sleep(interval)
                    continue
                submit_dict = {
                    "id": current_id,
                    "generation": current_generation,
                }
                
            # Submit response via thread
            self.submit_queue.put(submit_dict)
            
            # Reset states
            current_id = None
            current_payload = None
            current_generation = None
            return_error = None
            loop_retry = 0
                


if __name__ == "__main__":
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument('-i', '--interval', action="store", required=False, type=int, default=2, help="The amount of seconds with which to check if there's new prompts to generate")
    arg_parser.add_argument('-a', '--api_key', action="store", required=False, type=str, help="The horde API key")
    arg_parser.add_argument('-n', '--kai_name', action="store", required=False, type=str, help="The server name. It will be shown to the world and there can be only one.")
    arg_parser.add_argument('-k', '--kai_url', action="store", required=False, type=str, help="The LamaCpp server URL. Where the bridge will get its generations from.")
    arg_parser.add_argument('-c', '--cluster_url', action="store", required=False, type=str, help="The KoboldAI Cluster URL. Where the bridge will pickup prompts and send the finished generations.")
    arg_parser.add_argument('--debug', action="store_true", default=False, help="Show debugging messages.")
    arg_parser.add_argument('--priority_usernames',type=str, action='append', required=False, help="Usernames which get priority use in this server. The owner's username is always in this list.")
    arg_parser.add_argument('-v', '--verbosity', action='count', default=0, help="The default logging level is ERROR or higher. This value increases the amount of logging seen in your screen")
    arg_parser.add_argument('-q', '--quiet', action='count', default=0, help="The default logging level is ERROR or higher. This value decreases the amount of logging seen in your screen")
    arg_parser.add_argument('--log_file', action='store_true', default=False, help="If specified will dump the log to the specified file")
    args = arg_parser.parse_args()
    set_logger_verbosity(args.verbosity)
    if args.log_file:
        logger.add("llamacpp_bridge_log.log", retention="7 days", level="INFO")    # Automatically rotate too big file
    quiesce_logger(args.quiet)
    # test_logger()
    api_key = args.api_key if args.api_key else cd.api_key
    kai_name = args.kai_name if args.kai_name else cd.kai_name
    kai_url = args.kai_url if args.kai_url else cd.kai_url
    horde_url = args.cluster_url if args.cluster_url else cd.cluster_url
    priority_usernames = args.priority_usernames if args.priority_usernames else cd.priority_usernames
    logger.init(f"{kai_name} Instance", status="Started")
    
    binst = kai_bridge()
    try:                
        binst.bridge(
            interval = args.interval, 
            api_key = api_key, 
            kai_name= kai_name,
            kai_url = kai_url, 
            horde_url = horde_url, 
            priority_usernames=priority_usernames,
        )
    except KeyboardInterrupt:
        logger.info(f"Keyboard Interrupt Received. Ending Process")
    
    binst.stop()
        
    logger.init(f"{kai_name} Instance", status="Stopped")
