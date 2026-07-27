#!/bin/bash
curl --form "key=$1" --form "sym=@$2" http://example.com/symupload
