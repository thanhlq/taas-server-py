# Test kafka messaging serialization

- Test nodejs services in taas-server-js working fine, configs in taas-server-js/.env
- Test python services in taas-server-py working fine, config in taas-server-py/.env
- Testing user registration flow
- Required kafka, redis,... runing

## 0. Test Steps

1. Start the fastapi api: taas-server-py/start_fastapi_ews_api.sh
- or start the litestar: taas-server-py/start_litestar_ews_api.sh

2. start the worker
- taas-server-py/start_worker.sh

3. start the outbox:
- taas-server-py/start_outbox.sh

4. start nodejs worker (kafkajs client)
- taas-server-js/demos/messaging_kafka_demo/start-consumer.sh

5. go to taas-server-py/tests/e2e/test-user-register, execute:

```bash
uv run python test_register_new_user.py
```

## 1. Test schema-registry-avro serialization

- update configuration in .env in both python and nodejs, then execute test steps

## 2. Test msgpack serialization

- update configuration in .env in both python and nodejs, then execute test steps

## 3. Test json serialization

- update configuration in .env in both python and nodejs, then execute test steps

## 4. Test with nodejs confluent kafka client implementation

- in test steps, replace step 4 with: taas-server-js/demos/messaging_kafka_demo/start-consumer.sh kafka-cp
- repeat test 1, 2, and 3

## 5. Test another nodejs porting (kafkajs & kafka-cp)

- by replace the step 4, by this source code: /Users/thanhle/git/floin_kaspa/floin-authorizer/demos/messaging_kafka_demo
- and use the start kafka client script in this: start-authorizer-test.sh (default kafkajs)
- repeat test 1, 2, and 3
- test kafka-cp, start-authorizer-test.sh kafka-cp -> then repeat test 1, 2, 3

## 6. Test litestar api service

- In test steps, instead of using start_fastapi_ews_api.sh, start litestar api services by: start_litestar_ews_api.sh
- and repeat test 1, 2, 3, 4
