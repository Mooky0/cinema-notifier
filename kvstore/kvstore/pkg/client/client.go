package client

import (
	"bytes"
	"encoding/json"
	"fmt"
	"kvstore/pkg/api" // This is needed to use our own key-value store API.
	"net/http"
	"net/url"
)

type client struct {
	url string
}

func NewClient(addr string) Client {
	return &client{url: "http://" + addr}
}

func (c *client) Get(key string) (api.VersionedValue, error) {
	//this will append the query parameter formatted to the url
	uri, _ := url.Parse(c.url + "/api/get")
	q := uri.Query()
	q.Set("id", key)
	uri.RawQuery = q.Encode()
	r, err := http.Get(uri.String())
	if err != nil {
		return api.VersionedValue{}, err
	}
	defer r.Body.Close()

	if r.StatusCode != http.StatusOK {
		return api.VersionedValue{}, fmt.Errorf("HTTP error: %s", r.Status)
	}

	var ret api.VersionedValue

	decoder := json.NewDecoder(r.Body)
	decoder.DisallowUnknownFields()

	if err := decoder.Decode(&ret); err != nil {
		return api.VersionedValue{}, fmt.Errorf("failed to decode JSON: %w", err)
	}

	return ret, nil
}

func (c *client) Put(vkv api.VersionedKeyValue) error {
	jsonData, err := json.Marshal(vkv)
	if err != nil {
		return fmt.Errorf("failed to marshal JSON: %w", err)
	}

	uri, _ := url.Parse(c.url + "/api/put")

	r, err := http.Post(uri.String(), "application/json", bytes.NewBuffer(jsonData))
	if err != nil {
		return fmt.Errorf("POST request failed: %w", err)
	}

	defer r.Body.Close()

	if r.StatusCode != http.StatusOK {
		return fmt.Errorf("Server returned error: %s", err)
	}

	return nil
}

func (c *client) List() ([]api.VersionedKeyValue, error) {
	uri, _ := url.Parse(c.url + "/api/list")
	r, err := http.Get(uri.String())
	if err != nil || r.StatusCode != http.StatusOK {
		return []api.VersionedKeyValue{}, err
	}

	var ret []api.VersionedKeyValue

	decoder := json.NewDecoder(r.Body)
	decoder.DisallowUnknownFields()

	if err := decoder.Decode(&ret); err != nil {
		return []api.VersionedKeyValue{}, fmt.Errorf("failed to decode JSON: %w", err)
	}

	return ret, nil
}

func (c *client) Reset() error {
	uri, _ := url.Parse(c.url + "/api/reset")
	r, err := http.Get(uri.String())
	if err != nil || r.StatusCode != http.StatusOK {
		return err
	}
	return nil
}
