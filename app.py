import json
import logging
from io import StringIO
from src.controllers import health_controller, insert_controller

def get_configuration():
    """_summary_
    Load JSON with configuration
    :return: List with configuration
    """
    with open("config/config_health.json", "r", encoding="utf-8") as config_file:
        return json.load(config_file)


def context(context_outcome):
    """
    Emulate lambda Context.

    :param context_outcome: Dict with the context outcome
    :return: The context emulated object with the properties defined on context_oucome
    """
    response = type('new', (object,), context_outcome)
    seqs = tuple, list, set, frozenset
    for i, j in context_outcome.items():
        if isinstance(j, dict):
            setattr(response, i, context(j))
        elif isinstance(j, seqs):
            setattr(response, i,
                    type(j)(context(sj) if isinstance(sj, dict) else sj for sj in j))
        else:
            setattr(response, i, j)
    return response


def lambda_handler(event, context):
    """
    Handle events from workflow.

    Args:
        event (dict): Dict with event data
        context (dict): Dict with the response of the Lambda

    Returns:
        dict: Dict with the response of the Lambda
    """
    # Configure stringIO object to catch all events in the excecution
    # handler and formatter to catch events and organice the output
    log_buffer = StringIO()
    handler = logging.StreamHandler(log_buffer)
    formatter = logging.Formatter("%(asctime)s - %(levelname)s:%(message)s")
    handler.setFormatter(formatter)
    
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    # Call the configuration for the smoke test
    config = get_configuration()

    if event and event.get("type", "") == config["events"]["health"]:
        return health_controller.main()
    else:
        response = insert_controller.main(
            log_buffer, logger, event, context)
        log_buffer.truncate(0)
        return response
# # LOCAL TESTING PURPOSES ONLY

if __name__ == '__main__':
    import sys
    import glob

    #events_path = r"/Users/jeusma/Documents/EVC-EVD/InteligenciaDigital/Git/NU0242001_DocIA_Lambda_MR/insert_bdtl_lambda/test/input/events/download"
    events_path = sys.argv[1] 
    events_files = glob.glob(events_path + "/*.json")

    Context = context({
             "invoked_function_arn":
  "arn:aws:lambda:eu-west-1:123456789012:function:ExampleLambdaFunctionResourceName-AULC3LB8Q02F",
             "log_group_name": "/aws/lambda/ExampleLambdaFunctionResourceName-AULC3LB8Q02F",
             "function_name": "ExampleLambdaFunctionResourceName-AULC3LB8Q02F",
             "function_version": "$LATEST"
         })

    for event_file in events_files:
        print(
            f" \n ------ Local Test For Event: {event_file} ------ \n ")
        with open(event_file, "r", encoding="utf-8") as file:
            event = json.load(file)
            print(
                f" \n ------ Response For Event: {event_file} ------ \n ",
                json.dumps(lambda_handler(event, Context), indent=2)
                )
