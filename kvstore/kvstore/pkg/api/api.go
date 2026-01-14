package api

import "encoding/json"

type VersionedValue struct {
	Value   json.RawMessage `json:"value"`
	Version int             `json:"version"`
}

type VersionedKeyValue struct {
	Key string `json:"key"`
	VersionedValue
}
